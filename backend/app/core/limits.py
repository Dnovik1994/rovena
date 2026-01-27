from __future__ import annotations

from datetime import datetime, timezone
import logging

from redis import Redis

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _invite_key(user_id: int, now: datetime) -> str:
    return f"invites:{user_id}:{now.date().isoformat()}"


def get_daily_invites(user_id: int, client: Redis | None = None) -> int:
    now = datetime.now(timezone.utc)
    client = client or get_redis_client()
    try:
        value = client.get(_invite_key(user_id, now))
    except Exception:  # noqa: BLE001
        logger.exception("Failed to fetch daily invite counter")
        return 0
    return int(value or 0)


def increment_daily_invites(user_id: int, amount: int = 1, client: Redis | None = None) -> None:
    now = datetime.now(timezone.utc)
    client = client or get_redis_client()
    key = _invite_key(user_id, now)
    try:
        client.incrby(key, amount)
        client.expire(key, 86400)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to update daily invite counter")
