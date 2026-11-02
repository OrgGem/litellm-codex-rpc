import asyncio
import json


class StdioTransport:
    def __init__(self, process):
        self.process = process

    async def send(self, message):
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        await self.process.stdin.drain()

    async def recv(self):
        line = await self.process.stdout.readline()
        if not line:
            raise ConnectionError("Codex subprocess exited")
        return json.loads(line)

    async def close(self):
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), 3)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


async def open_stdio(config):
    # Codex alone reads its authentication. stderr is discarded to avoid leaking content.
    p = await asyncio.create_subprocess_exec(
        "codex",
        "app-server",
        "--listen",
        "stdio://",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        limit=4 * 1024 * 1024,
    )
    return StdioTransport(p)
