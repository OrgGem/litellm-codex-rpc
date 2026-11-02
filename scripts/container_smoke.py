"""Run the built nonroot Proxy image against a local fixture over a shared Unix socket."""

import asyncio
import os
import socket
import sys
import tempfile
from pathlib import Path

import httpx
from websockets.asyncio.server import unix_serve

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests"))
from test_rpc import Server


async def docker(*args):
    p = await asyncio.create_subprocess_exec(
        "docker",
        "--host=unix:///var/run/docker.sock",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    out, err = await p.communicate()
    if p.returncode:
        raise RuntimeError(err.decode())
    return (out + err).decode().strip()


async def main():
    fixture = Server()
    with tempfile.TemporaryDirectory(dir="/workspace") as directory:
        os.chmod(directory, 0o750)
        path = directory + "/codex.sock"
        async with unix_serve(fixture.handle, path):
            os.chmod(path, 0o660)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            container = await docker(
                "run",
                "-d",
                "--group-add",
                str(os.getgid()),
                "-p",
                f"127.0.0.1:{port}:4000",
                "--mount",
                f"type=bind,src={directory},dst=/run/codex,readonly",
                "-e",
                "LITELLM_MASTER_KEY=sk-container-test-only",
                "litellm-codex-rpc:0.2.0",
            )
            try:
                async with httpx.AsyncClient(
                    base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10
                ) as client:
                    for attempt in range(600):
                        if attempt % 10 == 0:
                            state = await docker(
                                "inspect", "--format", "{{.State.Running}}", container
                            )
                            if state != "true":
                                raise RuntimeError(
                                    "Container exited: "
                                    + await docker("logs", container)
                                )
                        try:
                            if (
                                await client.get("/health/liveliness")
                            ).status_code == 200:
                                break
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.1)
                    else:
                        raise RuntimeError(
                            "Container failed startup: "
                            + await docker("logs", container)
                        )
                    body = {
                        "model": "codex-default",
                        "messages": [{"role": "user", "content": "container-text"}],
                    }
                    r = await client.post(
                        "/v1/chat/completions",
                        json=body,
                        headers={"Authorization": "Bearer sk-container-test-only"},
                    )
                    assert r.status_code == 200, r.text
                    assert (
                        r.json()["choices"][0]["message"]["content"] == "container-text"
                    )
                    async with client.stream(
                        "POST",
                        "/v1/chat/completions",
                        json={**body, "stream": True},
                        headers={"Authorization": "Bearer sk-container-test-only"},
                    ) as r:
                        lines = [
                            line
                            async for line in r.aiter_lines()
                            if line.startswith("data:")
                        ]
                        assert any("container-text" in line for line in lines)
                        assert lines[-1] == "data: [DONE]"
                    print(
                        "Nonroot container, shared Unix socket, authorized completion and SSE: PASS"
                    )
            finally:
                await docker("rm", "-f", container)
                await fixture.close()


asyncio.run(main())
