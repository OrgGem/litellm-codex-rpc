import json

from websockets.asyncio.client import connect


class WebSocketTransport:
    def __init__(self, connection):
        self.connection = connection

    async def send(self, message):
        await self.connection.send(json.dumps(message))

    async def recv(self):
        return json.loads(await self.connection.recv())

    async def close(self):
        await self.connection.close()


async def open_websocket(config):
    headers = (
        {"Authorization": "Bearer " + config.ws_token} if config.ws_token else None
    )
    return WebSocketTransport(
        await connect(
            config.ws_url,
            additional_headers=headers,
            open_timeout=config.connect_timeout,
            max_queue=16,
            max_size=4 * 1024 * 1024,
            proxy=None,
        )
    )
