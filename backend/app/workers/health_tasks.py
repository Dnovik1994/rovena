"""Periodic system-health checks with Telegram notifications."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.workers import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.health_tasks.check_system_health")
def check_system_health() -> dict:
    """Check Redis and DB availability; notify on failure."""
    from app.core.redis_client import get_sync_redis
    from app.core.database import SessionLocal
    from app.services.notification_service import send_notification_sync
    from sqlalchemy import text

    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    problems: list[str] = []

    # Check Redis
    try:
        redis = get_sync_redis()
        if redis is None:
            problems.append("Redis client unavailable (no URL configured)")
        else:
            redis.ping()
    except Exception as exc:
        problems.append(f"Redis ping failed: {exc}")

    # Check DB
    try:
        with SessionLocal() as session:
            session.execute(text("SELECT 1"))
    except Exception as exc:
        problems.append(f"DB SELECT 1 failed: {exc}")

    if problems:
        for problem in problems:
            message = (
                f"🔴 Система: компонент недоступен\n"
                f"📝 Причина: {problem}\n"
                f"🕐 {now}"
            )
            try:
                send_notification_sync("system_health", message)
            except Exception:
                logger.exception("Failed to send system_health notification")

    return {"status": "unhealthy" if problems else "healthy", "problems": problems}
