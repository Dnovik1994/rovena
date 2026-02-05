import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, int] = {}

    async def connect(self, websocket: WebSocket, user_id: int) -> None:
        await websocket.accept()
        self._connections[websocket] = user_id
        logger.info("WS connected | user_id=%s | total=%s", user_id, len(self._connections))

    def disconnect(self, websocket: WebSocket) -> None:
        user_id = self._connections.pop(websocket, None)
        logger.info("WS disconnected | user_id=%s | total=%s", user_id, len(self._connections))

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> None:
        """Send a message only to connections belonging to a specific user."""
        message = json.dumps(payload)
        stale: list[WebSocket] = []
        for connection, conn_user_id in list(self._connections.items()):
            if conn_user_id != user_id:
                continue
            try:
                await connection.send_text(message)
            except Exception as exc:  # noqa: BLE001
                logger.info("WebSocket send failed", extra={"user_id": conn_user_id, "error": str(exc)})
                stale.append(connection)
        for connection in stale:
            self._connections.pop(connection, None)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Broadcast to all connected clients. Use send_to_user for user-specific messages."""
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
            loop = asyncio.get_running_loop()
            loop.create_task(self._dispatch_sync(payload))
        except RuntimeError:
            asyncio.run(self._dispatch_sync(payload))

    async def _dispatch_sync(self, payload: dict[str, Any]) -> None:
        """Route sync broadcasts to per-user delivery when user_id is present."""
        user_id = payload.get("user_id")
        if user_id is not None:
            await self.send_to_user(user_id, payload)
        else:
            await self.broadcast(payload)

    def get_user_id(self, websocket: WebSocket) -> int | None:
        return self._connections.get(websocket)

    @property
    def connection_count(self) -> int:
        return len(self._connections)


manager = WebSocketManager()
