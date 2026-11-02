import asyncio
from dataclasses import replace

import pytest
from test_rpc import fixture_server

from litellm_codex_rpc.errors import ProviderError
from litellm_codex_rpc.provider import CodexRPCProvider
from litellm_codex_rpc.rpc.client import RPCClient


async def test_stream_deadline_after_first_delta(tmp_path):
    async with fixture_server(tmp_path, "unix") as (_, config):
        provider = CodexRPCProvider(replace(config, request_timeout=0.1))
        stream = provider.astreaming(
            "codex-default", [{"role": "user", "content": "slow"}]
        )
        try:
            assert (await anext(stream))["text"] == "slow"
            with pytest.raises(ProviderError) as error:
                await asyncio.wait_for(anext(stream), 0.5)
            assert error.value.category == "timeout"
        finally:
            await stream.aclose()
            await provider.aclose()


class Wire:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.sent = []

    async def send(self, message):
        self.sent.append(message)

    async def recv(self):
        value = await self.messages.get()
        if isinstance(value, Exception):
            raise value
        return value

    async def close(self):
        pass


async def test_disconnect_preserves_received_events():
    wire = Wire()
    client = RPCClient(wire, 0.1)
    await wire.messages.put(
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}}
    )
    await wire.messages.put(ConnectionError())
    await asyncio.sleep(0.01)
    try:
        event = client.events.get_nowait()
        assert isinstance(event, dict) and event["method"] == "turn/completed"
    finally:
        await client.close()


async def test_invalid_rpc_parameters_are_client_error():
    wire = Wire()
    client = RPCClient(wire, 0.1)
    task = asyncio.create_task(client.request("turn/start", {}))
    await asyncio.sleep(0)
    await wire.messages.put(
        {
            "id": wire.sent[0]["id"],
            "error": {"code": -32602, "message": "/private/credential/path"},
        }
    )
    try:
        with pytest.raises(ProviderError) as error:
            await task
        assert error.value.status_code == 400
        assert "/private" not in str(error.value)
    finally:
        await client.close()


@pytest.mark.parametrize(
    "option", ["top_p", "stop", "seed", "logprobs", "tools", "stream_options"]
)
async def test_unsupported_direct_options(option):
    provider = CodexRPCProvider()
    try:
        with pytest.raises(ProviderError) as error:
            await provider.acompletion(
                "codex-default",
                [{"role": "user", "content": "hello"}],
                **{option: True},
            )
        assert error.value.status_code == 400
    finally:
        await provider.aclose()


async def test_shutdown_interrupts_stream_paused_between_chunks(tmp_path):
    async with fixture_server(tmp_path, "unix") as (server, config):
        provider = CodexRPCProvider(config)
        stream = provider.astreaming(
            "codex-default", [{"role": "user", "content": "slow"}]
        )
        assert (await anext(stream))["text"] == "slow"
        await provider.aclose()
        await asyncio.wait_for(server.interrupted.wait(), 0.5)
        await stream.aclose()
        with pytest.raises(ProviderError):
            await provider.acompletion(
                "codex-default", [{"role": "user", "content": "hello"}]
            )


async def test_write_errors_are_safe_and_terminal():
    class BrokenWire(Wire):
        async def send(self, message):
            raise OSError("secret socket /private/secret.sock")

    wire = BrokenWire()
    client = RPCClient(wire, 1)
    try:
        for _ in range(2):
            with pytest.raises(ProviderError) as error:
                await asyncio.wait_for(client.request("initialize", {}), 0.2)
            assert error.value.category == "connection"
            assert "/private" not in str(error.value)
        assert not client.pending
    finally:
        await client.close()


async def test_rpc_deadline_includes_stalled_write():
    class StalledWire(Wire):
        async def send(self, message):
            await asyncio.Event().wait()

    client = RPCClient(StalledWire(), 0.05)
    try:
        with pytest.raises(ProviderError) as error:
            await asyncio.wait_for(client.request("initialize", {}), 0.2)
        assert error.value.category == "timeout"
        assert not client.pending
    finally:
        await client.close()


async def test_malformed_payload_is_safe_protocol_error(monkeypatch):
    from litellm_codex_rpc.backends.base import Request
    from litellm_codex_rpc.backends.rpc_backend import RPCBackend
    from litellm_codex_rpc.config import Config

    class MalformedClient:
        async def request(self, method, params):
            return {"account": {"type": "chatgpt"}} if method == "account/read" else {}

        async def close(self):
            pass

    async def connect():
        return MalformedClient()

    backend = RPCBackend(Config())
    monkeypatch.setattr(backend, "connect", connect)
    with pytest.raises(ProviderError) as error:
        await backend.completion(Request(None, "hi", "test"))
    assert error.value.category == "protocol"
    await backend.close()


async def test_backend_close_wakes_waiting_consumer(tmp_path):
    from litellm_codex_rpc.backends.base import Request
    from litellm_codex_rpc.backends.rpc_backend import RPCBackend

    async with fixture_server(tmp_path, "unix") as (server, config):
        backend = RPCBackend(config)
        stream = backend.stream(Request(None, "slow", "test"))
        assert (await anext(stream)).text == "slow"
        pending = asyncio.create_task(anext(stream))
        await backend.close()
        with pytest.raises(ProviderError) as error:
            await asyncio.wait_for(pending, 0.5)
        assert error.value.category == "cancelled"
        await asyncio.wait_for(server.interrupted.wait(), 0.5)
        await stream.aclose()


@pytest.mark.parametrize(
    "usage",
    [
        {"inputTokens": 1},
        {"inputTokens": -1, "outputTokens": 1, "totalTokens": 0},
        {"inputTokens": "secret", "outputTokens": 1, "totalTokens": 1},
    ],
)
def test_malformed_usage_is_safe(usage):
    from litellm_codex_rpc.converters.responses import usage_from_rpc

    with pytest.raises(ProviderError) as error:
        usage_from_rpc(usage)
    assert error.value.category == "protocol"
    assert "secret" not in str(error.value)


async def test_backend_close_before_producer_starts():
    from litellm_codex_rpc.backends.base import Request
    from litellm_codex_rpc.backends.rpc_backend import RPCBackend
    from litellm_codex_rpc.config import Config

    backend = RPCBackend(Config())
    stream = backend.stream(Request(None, "hi", "startup-race"))
    consumer = asyncio.create_task(anext(stream))
    # The consumer registers the producer but its coroutine has not run yet.
    await asyncio.sleep(0)
    await backend.close()
    with pytest.raises(ProviderError) as error:
        await asyncio.wait_for(consumer, 0.2)
    assert error.value.category == "cancelled"
    await stream.aclose()


@pytest.mark.parametrize("fail", [False, True])
async def test_backend_close_with_full_output_queue(monkeypatch, fail):
    from litellm_codex_rpc.backends.base import Event, Request
    from litellm_codex_rpc.backends.rpc_backend import RPCBackend
    from litellm_codex_rpc.config import Config

    backend = RPCBackend(Config())
    ready = asyncio.Event()

    async def execute(request, emit):
        for _ in range(17):
            await emit(Event(text="queued"))
        ready.set()
        if fail:
            raise ProviderError("protocol", "Synthetic failure")

    monkeypatch.setattr(backend, "_execute", execute)
    stream = backend.stream(Request(None, "hi", "full-queue"))
    assert (await anext(stream)).text == "queued"
    await asyncio.wait_for(ready.wait(), 0.2)
    await backend.close()
    with pytest.raises(ProviderError) as error:
        await asyncio.wait_for(anext(stream), 0.2)
    assert error.value.category == "cancelled"
    await stream.aclose()
