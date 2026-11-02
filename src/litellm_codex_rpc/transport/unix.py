import os
import stat

from websockets.asyncio.client import unix_connect

from ..errors import ProviderError
from .websocket import WebSocketTransport


async def open_unix(config):
    s = os.stat(config.socket_path)
    if not stat.S_ISSOCK(s.st_mode) or s.st_mode & 0o007:
        raise ProviderError(
            "connection", "Codex socket must be a socket with no world permissions."
        )
    return WebSocketTransport(
        await unix_connect(
            config.socket_path,
            open_timeout=config.connect_timeout,
            max_queue=16,
            max_size=4 * 1024 * 1024,
        )
    )
