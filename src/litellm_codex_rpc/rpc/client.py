import asyncio
import itertools
import logging
from contextlib import suppress

from ..errors import ProviderError, remote_error


class RPCClient:
    """One connection per turn: disconnects cannot replay uncertain execution."""

    def __init__(self, transport, timeout):
        self.transport = transport
        self.timeout = timeout
        self.ids = itertools.count(1)
        self.pending = {}
        self.events = asyncio.Queue(64)
        self.write_lock = asyncio.Lock()
        self.reader = asyncio.create_task(self._read())
        self.closed = False

    async def send(self, message):
        async with self.write_lock:
            await self.transport.send(message)

    async def request(self, method, params):
        i = next(self.ids)
        logging.getLogger(__name__).debug(
            "codex_rpc_request", extra={"rpc_request_id": i, "rpc_method": method}
        )
        f = asyncio.get_running_loop().create_future()
        self.pending[i] = f
        try:
            await self.send({"id": i, "method": method, "params": params})
            return await asyncio.wait_for(f, self.timeout)
        except TimeoutError:
            raise ProviderError(
                "timeout", "Codex RPC request timed out.", 504
            ) from None
        finally:
            self.pending.pop(i, None)

    async def initialize(self):
        await self.request(
            "initialize",
            {"clientInfo": {"name": "litellm_codex_rpc", "version": "0.2.0"}},
        )
        await self.send({"method": "initialized", "params": {}})

    def _fail(self, error):
        for f in self.pending.values():
            if not f.done():
                f.set_exception(error)
        # Fail instead of dropping deltas or blocking RPC response dispatch.
        while not self.events.empty():
            self.events.get_nowait()
        self.events.put_nowait(error)

    async def _read(self):
        try:
            while True:
                m = await self.transport.recv()
                if not isinstance(m, dict):
                    raise ValueError("Invalid RPC envelope")
                if "method" in m and "id" in m:
                    await self.send(
                        {
                            "id": m["id"],
                            "error": {
                                "code": -32601,
                                "message": "Interactive operations are unsupported",
                            },
                        }
                    )
                    self._fail(
                        ProviderError(
                            "approval_required",
                            "Codex requested an unsupported interactive operation.",
                            400,
                        )
                    )
                    return
                if "method" in m:
                    try:
                        self.events.put_nowait(m)
                    except asyncio.QueueFull:
                        self._fail(
                            ProviderError(
                                "backpressure",
                                "Consumer cannot keep up with Codex events.",
                            )
                        )
                        return
                elif m.get("id") in self.pending:
                    f = self.pending[m["id"]]
                    if not f.done():
                        if "error" in m:
                            f.set_exception(remote_error(m["error"].get("data", {})))
                        elif "result" in m:
                            f.set_result(m["result"])
                        else:
                            f.set_exception(
                                ProviderError("protocol", "Malformed RPC response.")
                            )
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail(
                ProviderError(
                    "connection", "Codex connection lost; execution was not replayed."
                )
            )

    async def close(self):
        if self.closed:
            return
        self.closed = True
        self.reader.cancel()
        with suppress(asyncio.CancelledError):
            await self.reader
        self._fail(ProviderError("connection", "RPC connection closed."))
        await self.transport.close()
