import asyncio
import json
import os
from contextlib import asynccontextmanager

import pytest
from websockets.asyncio.server import serve, unix_serve

from litellm_codex_rpc.config import Config
from litellm_codex_rpc.converters.messages import convert
from litellm_codex_rpc.errors import ProviderError
from litellm_codex_rpc.provider import CodexRPCProvider


class Server:
    def __init__(self):
        self.count = 0
        self.interrupted = asyncio.Event()
        self.tasks = []
        self.start_params = []

    async def handle(self, ws):
        thread = None

        async def output(text):
            try:
                await ws.send(
                    json.dumps(
                        {
                            "method": "item/agentMessage/delta",
                            "params": {
                                "threadId": thread,
                                "turnId": "turn",
                                "delta": text,
                            },
                        }
                    )
                )
                if text == "slow":
                    await asyncio.sleep(10)
                else:
                    await asyncio.sleep(0.04)
                status = "failed" if text == "fail" else "completed"
                await ws.send(
                    json.dumps(
                        {
                            "method": "turn/completed",
                            "params": {
                                "threadId": thread,
                                "turn": {
                                    "id": "turn",
                                    "status": status,
                                    "error": {"codexErrorInfo": "rateLimitExceeded"},
                                },
                            },
                        }
                    )
                )
            except Exception:
                pass

        try:
            async for raw in ws:
                m = json.loads(raw)
                method = m.get("method")
                result = {}
                if method == "initialized":
                    continue
                if method == "initialize":
                    result = {"serverInfo": {"version": "fixture"}}
                elif method == "thread/start":
                    self.count += 1
                    thread = str(self.count)
                    result = {"thread": {"id": thread}}
                    self.start_params.append(m["params"])
                elif method == "turn/start":
                    text = m["params"]["input"][0]["text"]
                    result = {"turn": {"id": "turn", "status": "inProgress"}}
                    if text == "disconnect":
                        await ws.close()
                        continue
                    await ws.send(json.dumps({"id": m["id"], "result": result}))
                    if text == "approval":
                        await ws.send(
                            json.dumps(
                                {
                                    "id": 999,
                                    "method": "item/commandExecution/requestApproval",
                                    "params": {"threadId": thread},
                                }
                            )
                        )
                    else:
                        t = asyncio.create_task(output(text))
                        self.tasks.append(t)
                    continue
                elif method == "turn/interrupt":
                    self.interrupted.set()
                elif method == "account/read":
                    result = {
                        "account": {"type": "chatgpt"},
                        "requiresOpenaiAuth": True,
                    }
                await ws.send(json.dumps({"id": m["id"], "result": result}))
        finally:
            pass

    async def close(self):
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)


@asynccontextmanager
async def fixture_server(tmp_path, transport):
    server = Server()
    if transport == "unix":
        path = str(tmp_path / "codex.sock")
        async with unix_serve(server.handle, path):
            os.chmod(path, 0o600)
            try:
                yield server, Config(socket_path=path, request_timeout=2)
            finally:
                await server.close()
    else:
        async with serve(server.handle, "127.0.0.1", 0) as sock:
            port = sock.sockets[0].getsockname()[1]
            try:
                yield (
                    server,
                    Config(
                        transport="websocket",
                        ws_url=f"ws://127.0.0.1:{port}",
                        request_timeout=2,
                    ),
                )
            finally:
                await server.close()


@pytest.mark.parametrize("transport", ["unix", "websocket"])
async def test_five_streams(tmp_path, transport):
    async with fixture_server(tmp_path, transport) as (s, c):
        p = CodexRPCProvider(c)

        async def run(i):
            chunks = [
                x
                async for x in p.astreaming(
                    "codex-default", [{"role": "user", "content": str(i)}]
                )
            ]
            assert chunks[0]["text"] == str(i)
            assert not chunks[0]["is_finished"]
            assert chunks[-1]["is_finished"]

        try:
            await asyncio.gather(*(run(i) for i in range(5)))
            assert s.count == 5
            assert all(
                x["approvalPolicy"] == "untrusted" and x["sandbox"] == "read-only"
                for x in s.start_params
            )
        finally:
            await p.aclose()


async def test_failures_reconnect_cancel(tmp_path):
    async with fixture_server(tmp_path, "unix") as (s, c):
        p = CodexRPCProvider(c)
        try:
            for text, category in [
                ("fail", "rate_limit"),
                ("disconnect", "connection"),
                ("approval", "approval_required"),
            ]:
                with pytest.raises(ProviderError) as error:
                    await p.acompletion(
                        "codex-default", [{"role": "user", "content": text}]
                    )
                assert error.value.category == category
            response = await p.acompletion(
                "codex-default", [{"role": "user", "content": "ok"}]
            )
            assert response.choices[0].message.content == "ok"
            stream = p.astreaming(
                "codex-default", [{"role": "user", "content": "slow"}]
            )
            first = await anext(stream)
            assert first["text"] == "slow"  # proves output before terminal event
            await stream.aclose()
            await asyncio.wait_for(s.interrupted.wait(), 1)
        finally:
            await p.aclose()


async def test_sync_in_existing_loop(tmp_path):
    async with fixture_server(tmp_path, "websocket") as (_, c):
        p = CodexRPCProvider(c)
        try:
            # fixture server stays on this loop; sync caller has its own existing loop.
            def run():
                async def active():
                    stream = p.streaming(
                        "codex-default", [{"role": "user", "content": "ok"}]
                    )
                    assert next(stream)["text"] == "ok"
                    assert list(stream)[-1]["is_finished"]
                    assert (
                        p.completion(
                            "codex-default", [{"role": "user", "content": "ok"}]
                        )
                        .choices[0]
                        .finish_reason
                        == "stop"
                    )

                asyncio.run(active())

            await asyncio.to_thread(run)
        finally:
            await p.aclose()


@pytest.mark.parametrize(
    "messages",
    [
        [{"role": "tool", "content": "x"}],
        [{"role": "user", "content": []}],
        [{"role": "assistant", "content": "x"}],
        [{"role": "user", "content": "x", "name": "x"}],
    ],
)
def test_reject_semantic_loss(messages):
    with pytest.raises(ProviderError):
        convert(messages)


def test_flatten_and_empty():
    assert convert([{"role": "user", "content": ""}]) == ""
    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "answer"},
    ]
    assert json.loads(convert(messages, True).split("\n", 1)[1]) == messages


@pytest.mark.parametrize(
    "kwargs",
    [
        {"request_timeout": 0},
        {"max_concurrent": 0},
        {"connect_timeout": float("nan")},
        {"transport": "raw"},
        {"models": []},
        {"transport": "websocket", "ws_url": "ws://remote:4500"},
    ],
)
def test_bad_config(kwargs):
    with pytest.raises(ProviderError):
        Config(**kwargs)


async def test_litellm_dispatch(tmp_path):
    import litellm

    async with fixture_server(tmp_path, "websocket") as (_, c):
        p = CodexRPCProvider(c)
        old = litellm.custom_provider_map
        litellm.custom_provider_map = [{"provider": "codex_rpc", "custom_handler": p}]
        try:
            r = await litellm.acompletion(
                model="codex_rpc/codex-default",
                messages=[{"role": "user", "content": "ok"}],
            )
            assert r.choices[0].message.content == "ok"
            stream = await litellm.acompletion(
                model="codex_rpc/codex-default",
                messages=[{"role": "user", "content": "ok"}],
                stream=True,
            )
            chunks = [x async for x in stream]
            assert any(x.choices[0].delta.content == "ok" for x in chunks)
            assert chunks[-1].choices[0].finish_reason == "stop"
        finally:
            litellm.custom_provider_map = old
            await p.aclose()


async def test_proxy_http(tmp_path):
    import socket
    import sys
    from pathlib import Path

    import httpx

    async with fixture_server(tmp_path, "websocket") as (_, c):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        env = dict(
            os.environ,
            CODEX_RPC_TRANSPORT="websocket",
            CODEX_RPC_WS_URL=c.ws_url,
            LITELLM_MASTER_KEY="sk-local-test-only",
        )
        logfile = tmp_path / "proxy.log"
        with logfile.open("wb") as log:
            p = await asyncio.create_subprocess_exec(
                str(Path(sys.executable).with_name("litellm")),
                "--config",
                "config.example.yaml",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                env=env,
                stdout=log,
                stderr=log,
            )
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10
                ) as client:
                    for _ in range(100):
                        if p.returncode is not None:
                            pytest.fail(logfile.read_text()[-5000:])
                        try:
                            r = await client.get("/health/liveliness")
                            if r.status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        pytest.fail("Proxy not ready: " + logfile.read_text()[-5000:])
                    body = {
                        "model": "codex-default",
                        "messages": [{"role": "user", "content": "ok"}],
                    }
                    r = await client.post("/v1/chat/completions", json=body)
                    assert r.status_code == 401
                    headers = {"Authorization": "Bearer sk-local-test-only"}
                    r = await client.post(
                        "/v1/chat/completions", json=body, headers=headers
                    )
                    assert r.status_code == 200, r.text
                    assert r.json()["choices"][0]["message"]["content"] == "ok"
                    r = await client.post(
                        "/v1/chat/completions",
                        json={
                            **body,
                            "tools": [
                                {
                                    "type": "function",
                                    "function": {
                                        "name": "unsafe",
                                        "parameters": {"type": "object"},
                                    },
                                }
                            ],
                        },
                        headers=headers,
                    )
                    assert r.status_code == 400, r.text
                    r = await client.post(
                        "/v1/chat/completions",
                        json={
                            **body,
                            "messages": [{"role": "user", "content": "fail"}],
                        },
                        headers=headers,
                    )
                    assert r.status_code == 429, r.text

                    async with client.stream(
                        "POST",
                        "/v1/chat/completions",
                        json={**body, "stream": True},
                        headers=headers,
                    ) as r:
                        assert r.status_code == 200
                        lines = [
                            line
                            async for line in r.aiter_lines()
                            if line.startswith("data:")
                        ]
                        assert any("ok" in line for line in lines)
                        assert lines[-1] == "data: [DONE]"
            finally:
                if p.returncode is None:
                    p.terminate()
                await asyncio.wait_for(p.wait(), 5)


async def test_timeout_and_pending_cancellation(tmp_path):
    from dataclasses import replace

    async with fixture_server(tmp_path, "unix") as (s, c):
        p = CodexRPCProvider(replace(c, request_timeout=0.15))
        try:
            with pytest.raises(ProviderError) as e:
                await p.acompletion(
                    "codex-default", [{"role": "user", "content": "slow"}]
                )
            assert e.value.category == "timeout"
            await asyncio.wait_for(s.interrupted.wait(), 1)
            s.interrupted.clear()
            task = asyncio.create_task(
                p.acompletion("codex-default", [{"role": "user", "content": "slow"}])
            )
            await asyncio.sleep(0.05)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(s.interrupted.wait(), 1)
        finally:
            await p.aclose()


async def test_rpc_out_of_order_and_timeout():
    from litellm_codex_rpc.rpc.client import RPCClient

    class Wire:
        def __init__(self):
            self.inbox = asyncio.Queue()
            self.sent = []

        async def send(self, m):
            self.sent.append(m)

        async def recv(self):
            return await self.inbox.get()

        async def close(self):
            pass

    t = Wire()
    c = RPCClient(t, 0.1)
    try:
        a = asyncio.create_task(c.request("a", {}))
        b = asyncio.create_task(c.request("b", {}))
        await asyncio.sleep(0)
        await t.inbox.put({"id": t.sent[1]["id"], "result": "b"})
        await t.inbox.put({"id": t.sent[0]["id"], "result": "a"})
        assert await a == "a"
        assert await b == "b"
        with pytest.raises(ProviderError):
            await c.request("timeout", {})
        assert not c.pending
    finally:
        await c.close()
