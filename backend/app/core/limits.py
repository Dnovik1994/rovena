from __future__ import annotations

from datetime import datetime, time, timezone
import logging

from redis import Redis

from app.core.settings import get_settings

logger = logging.getLogger(__name__)


def get_redis_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)


def _seconds_until_end_of_day(now: datetime) -> int:
    end_of_day = datetime.combine(now.date(), time(23, 59, 59), tzinfo=timezone.utc)
    delta = end_of_day - now
    return max(int(delta.total_seconds()), 1)


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
    ttl_seconds = _seconds_until_end_of_day(now)
    try:
        pipe = client.pipeline()
        pipe.incrby(key, amount)
        pipe.expire(key, ttl_seconds)
        pipe.execute()
    except Exception:  # noqa: BLE001
        logger.exception("Failed to update daily invite counter")
