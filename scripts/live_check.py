"""Run one billable text turn through a configured, authenticated external Codex."""

import asyncio
import uuid

from litellm_codex_rpc.backends.base import Request
from litellm_codex_rpc.backends.rpc_backend import RPCBackend
from litellm_codex_rpc.config import Config


async def main():
    config = Config.from_env()
    backend = RPCBackend(config)
    try:
        model = next(iter(config.models.values()))
        result = await backend.completion(
            Request(
                model, "Reply with exactly hello. Do not use tools.", uuid.uuid4().hex
            )
        )
        if not result.text:
            raise RuntimeError("Completed turn contained no text")
        print(
            "Authenticated text turn completed successfully; response content omitted."
        )
    finally:
        await backend.close()


asyncio.run(main())
