import asyncio
import itertools
import json
import logging
from contextlib import suppress

from websockets.exceptions import ConnectionClosed

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
        self.failure = None
        self.reader = asyncio.create_task(self._read())
        self.closed = False

    async def send(self, message):
        if self.failure:
            raise self.failure
        async with self.write_lock:
            if self.failure:
                raise self.failure
            await self.transport.send(message)

    async def request(self, method, params):
        if self.failure:
            raise self.failure
        i = next(self.ids)
        logging.getLogger(__name__).debug(
            "codex_rpc_request", extra={"rpc_request_id": i, "rpc_method": method}
        )
        future = asyncio.get_running_loop().create_future()
        self.pending[i] = future
        try:
            # Include write-lock admission and a stalled send in the RPC deadline.
            async with asyncio.timeout(self.timeout):
                try:
                    await self.send({"id": i, "method": method, "params": params})
                except (OSError, ConnectionError, ConnectionClosed):
                    self._fail(
                        ProviderError(
                            "connection",
                            "Cannot send to Codex; execution was not replayed.",
                        )
                    )
                return await future
        except TimeoutError:
            raise ProviderError(
                "timeout", "Codex RPC request timed out.", 504
            ) from None
        finally:
            self.pending.pop(i, None)
            # send() can fail after the reader has failed this future.
            if future.done() and not future.cancelled():
                future.exception()
            elif not future.done():
                future.cancel()

    async def initialize(self):
        await self.request(
            "initialize",
            {"clientInfo": {"name": "litellm_codex_rpc", "version": "0.2.0"}},
        )
        await self.send({"method": "initialized", "params": {}})

    async def next_event(self):
        if not self.events.empty():
            event = self.events.get_nowait()
        elif self.failure:
            raise self.failure
        else:
            event = await self.events.get()
        if isinstance(event, Exception):
            raise event
        return event

    def _fail(self, error):
        if self.failure:
            return
        self.failure = error
        for future in self.pending.values():
            if not future.done():
                future.set_exception(error)
        # Received events remain ordered and available even after a clean EOF.
        # If full, next_event will observe failure when the queue is drained.
        if not self.events.full():
            self.events.put_nowait(error)

    async def _read(self):
        try:
            while True:
                message = await self.transport.recv()
                if not isinstance(message, dict):
                    raise ValueError("Invalid RPC envelope")
                if "method" in message:
                    if not isinstance(message["method"], str) or not isinstance(
                        message.get("params", {}), dict
                    ):
                        raise ValueError("Invalid notification")
                    if "id" in message:
                        await self.send(
                            {
                                "id": message["id"],
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
                    try:
                        self.events.put_nowait(message)
                    except asyncio.QueueFull:
                        self._fail(
                            ProviderError(
                                "backpressure",
                                "Consumer cannot keep up with Codex events.",
                            )
                        )
                        return
                else:
                    request_id = message.get("id")
                    if not isinstance(request_id, (str, int)):
                        raise ValueError("Invalid RPC response ID")
                    future = self.pending.get(request_id)
                    if future is not None and not future.done():
                        if "error" in message:
                            error = message["error"]
                            if not isinstance(error, dict):
                                raise ValueError("Invalid RPC error")
                            future.set_exception(
                                remote_error(error.get("data", {}), error.get("code"))
                            )
                        elif "result" in message:
                            future.set_result(message["result"])
                        else:
                            raise ValueError("Malformed RPC response")
        except asyncio.CancelledError:
            raise
        except (ValueError, TypeError, json.JSONDecodeError):
            self._fail(ProviderError("protocol", "Malformed Codex RPC message."))
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
        self._fail(ProviderError("connection", "RPC connection closed."))
        self.reader.cancel()
        with suppress(asyncio.CancelledError):
            await self.reader
        await self.transport.close()
