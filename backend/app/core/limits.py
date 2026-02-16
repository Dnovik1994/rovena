from __future__ import annotations

from datetime import datetime, timezone
import logging

from redis import Redis

from app.core.redis_client import get_sync_redis_decoded

logger = logging.getLogger(__name__)


def get_redis_client() -> Redis | None:
    return get_sync_redis_decoded()


def _invite_key(user_id: int, now: datetime) -> str:
    return f"invites:{user_id}:{now.date().isoformat()}"


def get_daily_invites(user_id: int, client: Redis | None = None) -> int:
    now = datetime.now(timezone.utc)
    client = client or get_redis_client()
    if client is None:
        return 0
    try:
        value = client.get(_invite_key(user_id, now))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to fetch daily invite counter")
        return 0
    return int(value or 0)


def increment_daily_invites(user_id: int, amount: int = 1, client: Redis | None = None) -> None:
    now = datetime.now(timezone.utc)
    client = client or get_redis_client()
    if client is None:
        return
    key = _invite_key(user_id, now)
    try:
        client.incrby(key, amount)
        client.expire(key, 86400)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to update daily invite counter")
