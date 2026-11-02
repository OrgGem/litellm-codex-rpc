import asyncio
import logging
import time
from contextlib import suppress

from ..errors import ProviderError, remote_error
from ..rpc.client import RPCClient
from ..transport.stdio import open_stdio
from ..transport.unix import open_unix
from ..transport.websocket import open_websocket
from .base import Event

log = logging.getLogger(__name__)


class RPCBackend:
    def __init__(self, config):
        self.config = config
        self.slots = asyncio.Semaphore(config.max_concurrent)
        self.clients = set()
        self.producers = set()
        self.failed = False
        self.closed = False

    async def connect(self):
        if self.closed or (self.failed and not self.config.auto_reconnect):
            raise ProviderError("connection", "Backend closed or reconnect disabled.")
        try:
            t = await asyncio.wait_for(
                {"unix": open_unix, "websocket": open_websocket, "stdio": open_stdio}[
                    self.config.transport
                ](self.config),
                self.config.connect_timeout,
            )
            c = RPCClient(t, self.config.request_timeout)
            self.clients.add(c)
            try:
                await asyncio.wait_for(c.initialize(), self.config.connect_timeout)
            except BaseException:
                await c.close()
                self.clients.discard(c)
                raise
            return c
        except ProviderError as error:
            if error.category == "connection":
                self.failed = True
            raise
        except Exception:
            self.failed = True
            raise ProviderError(
                "connection",
                "Cannot connect to Codex; check transport, permissions and server version.",
            ) from None

    async def stream(self, request):
        # A single producer owns the deadline and turn lifecycle across all yields.
        # Consumers (including the sync bridge) may use a different Task per read.
        queue = asyncio.Queue(16)

        async def produce():
            try:
                await self._execute(request, queue.put)
            except Exception as error:
                await queue.put(error)
            else:
                await queue.put(None)

        def finished(task):
            self.producers.discard(task)
            if task.cancelled():
                # Runs even when cancelled before produce() starts, or while
                # publishing an error/EOF into a full output queue.
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(
                    ProviderError("cancelled", "Codex stream closed.", 499)
                )

        producer = asyncio.create_task(produce())
        self.producers.add(producer)
        producer.add_done_callback(finished)
        try:
            while True:
                event = await queue.get()
                if event is None:
                    return
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            producer.cancel()
            with suppress(asyncio.CancelledError):
                await producer

    async def _execute(self, request, emit):
        c = None
        thread = None
        turn = None
        complete = False
        started = time.monotonic()
        first = None
        status = "failed"
        try:
            async with asyncio.timeout(self.config.request_timeout):
                async with self.slots:
                    c = await self.connect()
                    account = await c.request("account/read", {"refreshToken": False})
                    if account.get("requiresOpenaiAuth") and not account.get("account"):
                        raise ProviderError(
                            "authentication",
                            "Authenticate the external Codex server.",
                            401,
                        )
                    # Safe baseline: no automatic approvals, read-only sandbox. Full tool
                    # suppression also requires the documented dedicated server configuration.
                    result = await c.request(
                        "thread/start",
                        {
                            "model": request.model,
                            "ephemeral": True,
                            "approvalPolicy": "untrusted",
                            "sandbox": "read-only",
                            "config": {
                                "features.shell_tool": False,
                                "features.unified_exec": False,
                                "features.apply_patch_freeform": False,
                                "web_search": "disabled",
                            },
                        },
                    )
                    thread = result["thread"]["id"]
                    if not isinstance(thread, str) or not thread:
                        raise ValueError("Invalid thread ID")
                    result = await c.request(
                        "turn/start",
                        {
                            "threadId": thread,
                            "input": [{"type": "text", "text": request.text}],
                        },
                    )
                    turn = result["turn"]["id"]
                    if not isinstance(turn, str) or not turn:
                        raise ValueError("Invalid turn ID")
                    usage = None
                    while True:
                        event = await c.next_event()
                        if isinstance(event, Exception):
                            raise event
                        p = event.get("params", {})
                        method = event["method"]
                        if p.get("threadId") != thread:
                            continue
                        event_turn = p.get("turnId") or p.get("turn", {}).get("id")
                        if event_turn and event_turn != turn:
                            continue
                        if method == "item/agentMessage/delta":
                            if not isinstance(p.get("delta"), str):
                                raise ValueError("Invalid text delta")
                            if first is None:
                                first = time.monotonic() - started
                            await emit(Event(text=p["delta"]))
                        elif method == "thread/tokenUsage/updated":
                            usage = p.get("tokenUsage", {}).get("last")
                        elif method == "item/started" and p.get("item", {}).get(
                            "type"
                        ) in {
                            "commandExecution",
                            "fileChange",
                            "mcpToolCall",
                            "dynamicToolCall",
                            "webSearch",
                        }:
                            raise ProviderError(
                                "approval_required",
                                "Internal tool execution is unsupported.",
                                400,
                            )
                        elif method == "turn/completed":
                            terminal = p["turn"]
                            if terminal["status"] == "interrupted":
                                raise ProviderError(
                                    "cancelled", "Codex turn interrupted.", 499
                                )
                            if terminal["status"] != "completed":
                                raise remote_error(terminal.get("error") or {})
                            complete = True
                            status = "completed"
                            await emit(Event(done=True, usage=usage))
                            return
        except (KeyError, TypeError, ValueError, AttributeError):
            status = "protocol"
            raise ProviderError(
                "protocol", "Malformed Codex response or event."
            ) from None
        except TimeoutError:
            status = "timeout"
            raise ProviderError("timeout", "Codex turn timed out.", 504) from None
        except asyncio.CancelledError:
            status = "cancelled"
            raise
        except ProviderError as e:
            status = e.category
            if e.category == "connection":
                self.failed = True
            raise
        finally:
            if c:
                if thread and turn and not complete:
                    with suppress(Exception):
                        await asyncio.wait_for(
                            c.request(
                                "turn/interrupt", {"threadId": thread, "turnId": turn}
                            ),
                            2,
                        )
                await c.close()
                self.clients.discard(c)
            log.info(
                "codex_turn",
                extra={
                    "request_id": request.request_id,
                    "model_alias": request.model_alias,
                    "backend": "rpc",
                    "transport": self.config.transport,
                    "thread_id": thread,
                    "turn_id": turn,
                    "duration": time.monotonic() - started,
                    "time_to_first_token": first,
                    "status": status,
                },
            )

    async def completion(self, request):
        text = ""
        usage = None
        async for event in self.stream(request):
            text += event.text
            usage = event.usage or usage
        return Event(text=text, done=True, usage=usage)

    async def health_check(self):
        c = await self.connect()
        try:
            return await c.request("account/read", {"refreshToken": False})
        finally:
            await c.close()
            self.clients.discard(c)

    async def list_models(self):
        c = await self.connect()
        try:
            return await c.request("model/list", {})
        finally:
            await c.close()
            self.clients.discard(c)

    async def close(self):
        self.closed = True
        producers = list(self.producers)
        for producer in producers:
            producer.cancel()
        await asyncio.gather(*producers, return_exceptions=True)
        await asyncio.gather(*(c.close() for c in list(self.clients)))
        self.clients.clear()
