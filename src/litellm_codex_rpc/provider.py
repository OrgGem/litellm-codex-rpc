import asyncio
import threading
import uuid

from litellm import CustomLLM

from .backends.base import Request
from .backends.rpc_backend import RPCBackend
from .config import Config
from .converters.messages import convert
from .converters.responses import chunk, response
from .errors import invalid


class CodexRPCProvider(CustomLLM):
    """Lazy worker loop bridges all four LiteLLM interfaces without nesting loops.

    Instantiate per process after fork. close()/aclose() releases the worker.
    Positional model/messages plus LiteLLM's keyword arguments match 1.80.7 dispatch.
    """

    def __init__(self, config=None):
        super().__init__()
        self.config = config or Config.from_env()
        self._lock = threading.Lock()
        self._loop = None
        self._backend = None
        self._thread = None

    def _ensure(self):
        with self._lock:
            if self._loop:
                return
            self.config = self.config or Config.from_env()
            self._loop = asyncio.new_event_loop()
            self._backend = RPCBackend(self.config)
            self._thread = threading.Thread(
                target=self._loop.run_forever, daemon=True, name="codex-rpc"
            )
            self._thread.start()

    def _request(self, model, messages, kwargs):
        self._ensure()
        alias = model.removeprefix("codex_rpc/")
        if alias not in self.config.models:
            raise invalid("Unknown model alias; configure CODEX_MODEL_MAP.")
        params = kwargs.get("optional_params") or {}
        if any(
            k not in {"stream", "stream_options", "extra_headers", "max_retries"}
            and v is not None
            for k, v in params.items()
        ):
            raise invalid(
                "Unsupported completion parameter: "
                + ",".join(
                    k
                    for k, v in params.items()
                    if k
                    not in {"stream", "stream_options", "extra_headers", "max_retries"}
                    and v is not None
                )
            )
        for key in (
            "tools",
            "tool_choice",
            "functions",
            "function_call",
            "response_format",
            "temperature",
            "max_tokens",
            "max_completion_tokens",
            "reasoning_effort",
        ):
            if kwargs.get(key) is not None:
                raise invalid("Unsupported completion parameter: " + key)
        return Request(
            self.config.models[alias],
            convert(messages, self.config.flatten),
            (kwargs.get("litellm_params") or {}).get("litellm_call_id")
            or uuid.uuid4().hex,
            alias,
        )

    def _submit(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def completion(self, model, messages, **kwargs):
        request = self._request(model, messages, kwargs)
        return response(model, self._submit(self._backend.completion(request)).result())

    async def acompletion(self, model, messages, **kwargs):
        request = self._request(model, messages, kwargs)
        return response(
            model,
            await asyncio.wrap_future(self._submit(self._backend.completion(request))),
        )

    def streaming(self, model, messages, **kwargs):
        request = self._request(model, messages, kwargs)
        stream = self._backend.stream(request)
        try:
            while True:
                try:
                    yield chunk(self._submit(anext(stream)).result())
                except StopAsyncIteration:
                    return
        finally:
            self._submit(stream.aclose()).result()

    async def astreaming(self, model, messages, **kwargs):
        request = self._request(model, messages, kwargs)
        stream = self._backend.stream(request)
        try:
            while True:
                try:
                    yield chunk(await asyncio.wrap_future(self._submit(anext(stream))))
                except StopAsyncIteration:
                    return
        finally:
            # Let cancellation finish in the worker before closing the async generator.
            async def finish():
                while stream.ag_running:
                    await asyncio.sleep(0.01)
                await stream.aclose()

            await asyncio.shield(asyncio.wrap_future(self._submit(finish())))

    def close(self):
        with self._lock:
            if self._loop is None:
                return

            async def shutdown():
                await self._backend.close()
                pending = [
                    t
                    for t in asyncio.all_tasks()
                    if t is not asyncio.current_task() and not t.done()
                ]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)

            self._submit(shutdown()).result()
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join()
            self._loop.close()
            self._loop = None

    async def aclose(self):
        await asyncio.to_thread(self.close)


codex_rpc_provider = CodexRPCProvider()
