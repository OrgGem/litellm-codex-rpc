from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Request:
    model: str | None
    text: str
    request_id: str
    model_alias: str = ""


@dataclass
class Event:
    text: str = ""
    done: bool = False
    usage: dict | None = None


class CodexBackend(Protocol):
    async def completion(self, request: Request) -> Event: ...
    def stream(self, request: Request) -> AsyncIterator[Event]: ...
    async def list_models(self): ...
    async def health_check(self): ...
    async def close(self): ...
