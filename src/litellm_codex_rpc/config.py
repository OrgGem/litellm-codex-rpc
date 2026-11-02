import json
import math
import os
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from .errors import invalid


@dataclass(frozen=True)
class Config:
    transport: str = "unix"
    socket_path: str = "/run/codex/codex.sock"
    ws_url: str = ""
    ws_token: str | None = field(default=None, repr=False)
    connect_timeout: float = 10
    request_timeout: float = 300
    max_concurrent: int = 5
    auto_reconnect: bool = True
    flatten: bool = False
    models: dict = field(default_factory=lambda: {"codex-default": None})

    def __post_init__(self):
        if self.transport not in {"unix", "websocket", "stdio"}:
            raise invalid("CODEX_RPC_TRANSPORT must be unix, websocket or stdio.")
        if not os.path.isabs(self.socket_path):
            raise invalid("CODEX_RPC_SOCKET_PATH must be absolute.")
        if self.transport == "websocket":
            u = urlsplit(self.ws_url)
            if (
                u.scheme not in {"ws", "wss"}
                or not u.hostname
                or u.username
                or u.password
            ):
                raise invalid(
                    "Set CODEX_RPC_WS_URL to a WebSocket URL without embedded credentials."
                )
            if u.hostname not in {"127.0.0.1", "localhost", "::1"} and (
                u.scheme != "wss" or not self.ws_token
            ):
                raise invalid(
                    "Remote WebSocket requires wss and CODEX_RPC_WS_TOKEN on a trusted network."
                )
        if (
            any(
                not math.isfinite(x) or x <= 0
                for x in (self.connect_timeout, self.request_timeout)
            )
            or self.max_concurrent < 1
        ):
            raise invalid("Timeouts and concurrency must be positive finite numbers.")
        if (
            not isinstance(self.models, dict)
            or not self.models
            or any(
                not isinstance(k, str)
                or not k
                or (v is not None and (not isinstance(v, str) or not v))
                for k, v in self.models.items()
            )
        ):
            raise invalid(
                "CODEX_MODEL_MAP must be an object mapping aliases to model names or null."
            )

    @classmethod
    def from_env(cls):
        def boolean(name, default):
            value = os.getenv(name, default).lower()
            if value not in {"true", "false"}:
                raise invalid(f"{name} must be true or false.")
            return value == "true"

        if os.getenv("CODEX_BACKEND", "rpc") != "rpc":
            raise invalid(
                "Legacy direct mode is unavailable: upstream licensing is unresolved."
            )
        if os.getenv("CODEX_RPC_SESSION_MODE", "stateless") != "stateless":
            raise invalid("Only stateless sessions are implemented.")
        if boolean("CODEX_RPC_ALLOW_INTERNAL_TOOLS", "false"):
            raise invalid(
                "Agent mode is not implemented; internal tools cannot be enabled."
            )
        try:
            return cls(
                transport=os.getenv("CODEX_RPC_TRANSPORT", "unix"),
                socket_path=os.getenv("CODEX_RPC_SOCKET_PATH", "/run/codex/codex.sock"),
                ws_url=os.getenv("CODEX_RPC_WS_URL", ""),
                ws_token=os.getenv("CODEX_RPC_WS_TOKEN"),
                connect_timeout=float(os.getenv("CODEX_RPC_CONNECT_TIMEOUT", "10")),
                request_timeout=float(os.getenv("CODEX_RPC_REQUEST_TIMEOUT", "300")),
                max_concurrent=int(os.getenv("CODEX_RPC_MAX_CONCURRENT_TURNS", "5")),
                auto_reconnect=boolean("CODEX_RPC_AUTO_RECONNECT", "true"),
                flatten=boolean("CODEX_RPC_ALLOW_PROMPT_FLATTENING", "false"),
                models=json.loads(
                    os.getenv("CODEX_MODEL_MAP", '{"codex-default":null}')
                ),
            )
        except (ValueError, TypeError):
            raise invalid("Invalid numeric setting or CODEX_MODEL_MAP JSON.") from None
