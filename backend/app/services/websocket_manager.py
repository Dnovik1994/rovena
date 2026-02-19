import asyncio
import json
import logging
from typing import Any

from fastapi import WebSocket

from app.core.redis_client import get_sync_redis

logger = logging.getLogger(__name__)

PING_INTERVAL_SECONDS = 30
PING_TIMEOUT_SECONDS = 10
REDIS_WS_CHANNEL = "ws:broadcast"

_DEFAULT_BROADCAST_CONCURRENCY = 100


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[WebSocket, int] = {}
        self._lock = asyncio.Lock()
        self._semaphore: asyncio.Semaphore | None = None

    def _get_semaphore(self) -> asyncio.Semaphore:
        """Lazily create the semaphore so it's bound to the running event loop."""
        if self._semaphore is None:
            try:
                from app.core.settings import get_settings
                limit = get_settings().ws_broadcast_concurrency
            except Exception:  # noqa: BLE001
                limit = _DEFAULT_BROADCAST_CONCURRENCY
            self._semaphore = asyncio.Semaphore(limit)
        return self._semaphore

    async def connect(self, websocket: WebSocket, user_id: int, *, accept: bool = True) -> None:
        if accept:
            await websocket.accept()
        async with self._lock:
            self._connections[websocket] = user_id
        logger.info("WS connected | user_id=%s | total=%s", user_id, len(self._connections))

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            user_id = self._connections.pop(websocket, None)
        logger.info("WS disconnected | user_id=%s | total=%s", user_id, len(self._connections))

    async def send_to_user(self, user_id: int, payload: dict[str, Any]) -> None:
        """Send a message only to connections belonging to a specific user."""
        message = json.dumps(payload)
        snapshot = list(self._connections.items())
        targets = [(ws, uid) for ws, uid in snapshot if uid == user_id]
        if not targets:
            return
        await self._send_concurrent(message, targets)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Broadcast to all connected clients. Use send_to_user for user-specific messages."""
        if not self._connections:
            return
        message = json.dumps(payload)
        snapshot = list(self._connections.items())
        await self._send_concurrent(message, snapshot)

    async def _send_concurrent(
        self,
        message: str,
        targets: list[tuple[WebSocket, int]],
    ) -> None:
        """Send *message* to all *targets* concurrently, then prune failures."""
        semaphore = self._get_semaphore()

        async def _guarded_send(ws: WebSocket) -> WebSocket | None:
            async with semaphore:
                try:
                    await ws.send_text(message)
                except Exception as exc:  # noqa: BLE001
                    logger.info("WebSocket send failed", extra={"error": str(exc)})
                    return ws
            return None

        results = await asyncio.gather(
            *(_guarded_send(ws) for ws, _ in targets),
            return_exceptions=True,
        )

        stale: list[WebSocket] = []
        for result in results:
            if isinstance(result, WebSocket):
                stale.append(result)
            elif isinstance(result, BaseException):
                logger.info("Unexpected error in concurrent send: %s", result)

        if stale:
            async with self._lock:
                for ws in stale:
                    self._connections.pop(ws, None)

    def broadcast_sync(self, payload: dict[str, Any]) -> None:
        """Broadcast from synchronous context (e.g. Celery tasks).

        If we are inside the uvicorn process with connected clients,
        dispatch directly.  Otherwise publish to Redis so the uvicorn
        process can relay the message to WebSocket clients.
        """
        # Try direct dispatch first (works in the uvicorn process)
        if self._connections:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._dispatch_sync(payload))
                return
            except RuntimeError:
                pass

        # Fallback: publish to Redis channel (works from Celery workers)
        self._publish_to_redis(payload)

    def _publish_to_redis(self, payload: dict[str, Any]) -> None:
        client = get_sync_redis()
        if client is None:
            logger.debug("broadcast_sync: no Redis client available, message dropped")
            return
        try:
            client.publish(REDIS_WS_CHANNEL, json.dumps(payload))
        except Exception:  # noqa: BLE001
            logger.exception("Failed to publish WS event to Redis")

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
