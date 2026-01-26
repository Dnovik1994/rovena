import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, int] = {}

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._connections[websocket] = user_id

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.pop(websocket, None)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        if not self._connections:
            return
        message = json.dumps(payload)
        stale: list[WebSocket] = []
        for connection in list(self._connections.keys()):
            try:
                await connection.send_text(message)
            except Exception as exc:  # noqa: BLE001
                logger.info("WebSocket send failed", extra={"error": str(exc)})
                stale.append(connection)
        for connection in stale:
            self._connections.pop(connection, None)

    def broadcast_sync(self, payload: dict[str, Any]) -> None:
        try:
            asyncio.run(self.broadcast(payload))
        except RuntimeError:
            loop = asyncio.get_event_loop()
            loop.create_task(self.broadcast(payload))


manager = WebSocketManager()
