"""FloodWait throttle — automatic slowdown when FloodWait rate is high.

Redis keys:
- ``warming:flood_count:YYYY-MM-DD`` — daily FloodWait counter
- ``warming:throttle_mode`` — current throttle mode (normal / slow / paused)
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from app.core.database import SessionLocal
from app.core.redis_client import get_sync_redis_decoded
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.services.notification_service import send_notification_sync
from app.workers import celery_app

logger = logging.getLogger(__name__)

THROTTLE_NORMAL = "normal"  # < 5%: normal pauses
THROTTLE_SLOW = "slow"  # 8-15%: pauses x2
THROTTLE_PAUSED = "paused"  # > 15%: pause everything for 1 hour

_FLOOD_COUNT_KEY_PREFIX = "warming:flood_count"
_THROTTLE_MODE_KEY = "warming:throttle_mode"
_FLOOD_COUNT_TTL = 86400 * 2  # 2 days
_THROTTLE_MODE_TTL = 3600  # 1 hour


def increment_flood_counter() -> None:
    """Increment today's FloodWait counter in Redis."""
    redis = get_sync_redis_decoded()
    if redis is None:
        return
    key = f"{_FLOOD_COUNT_KEY_PREFIX}:{date.today().isoformat()}"
    redis.incr(key)
    redis.expire(key, _FLOOD_COUNT_TTL)


def get_flood_rate() -> float:
    """Return the fraction of warming/cooldown accounts that hit FloodWait today."""
    redis = get_sync_redis_decoded()
    flood_count = int(redis.get(f"{_FLOOD_COUNT_KEY_PREFIX}:{date.today().isoformat()}") or 0) if redis else 0

    with SessionLocal() as db:
        total_warming = (
            db.query(TelegramAccount)
            .filter(
                TelegramAccount.status.in_(
                    [TelegramAccountStatus.warming, TelegramAccountStatus.cooldown]
                )
            )
            .count()
        )

    if total_warming == 0:
        return 0.0
    return flood_count / total_warming


def get_throttle_mode() -> str:
    """Return the current throttle mode from Redis (defaults to normal)."""
    redis = get_sync_redis_decoded()
    if redis is None:
        return THROTTLE_NORMAL
    return redis.get(_THROTTLE_MODE_KEY) or THROTTLE_NORMAL


@celery_app.task(bind=True, soft_time_limit=30, time_limit=60)
def update_warming_throttle(self) -> None:
    """Evaluate current FloodWait rate and update throttle mode in Redis."""
    rate = get_flood_rate()
    current_mode = get_throttle_mode()

    if rate > 0.15:
        new_mode = THROTTLE_PAUSED
    elif rate > 0.08:
        new_mode = THROTTLE_SLOW
    else:
        new_mode = THROTTLE_NORMAL

    if new_mode != current_mode:
        redis = get_sync_redis_decoded()
        if redis is not None:
            redis.set(_THROTTLE_MODE_KEY, new_mode, ex=_THROTTLE_MODE_TTL)
        logger.warning(
            "Warming throttle changed: %s -> %s (rate: %.1f%%)",
            current_mode,
            new_mode,
            rate * 100,
        )
        try:
            send_notification_sync(
                "flood_rate_threshold",
                f"\U0001f4ca \u0420\u0435\u0436\u0438\u043c \u043f\u0440\u043e\u0433\u0440\u0435\u0432\u0430 \u0438\u0437\u043c\u0435\u043d\u0451\u043d\n"
                f"\U0001f4c8 FloodWait rate: {rate:.1%}\n"
                f"\u26a1 {current_mode} \u2192 {new_mode}\n"
                f"\U0001f550 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            )
        except Exception:  # noqa: BLE001
            logger.exception("Failed to send throttle change notification")
