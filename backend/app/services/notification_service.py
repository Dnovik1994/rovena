"""Telegram Bot notification service with deduplication."""

from __future__ import annotations

import hashlib
import logging

import httpx

from app.core.database import SessionLocal
from app.core.redis_client import get_sync_redis
from app.models.admin_notification_setting import AdminNotificationSetting

logger = logging.getLogger(__name__)

# Mapping from event_type string to model field name
EVENT_TYPE_FIELD_MAP: dict[str, str] = {
    "account_banned": "notify_account_banned",
    "flood_wait": "notify_flood_wait",
    "warming_failed": "notify_warming_failed",
    "warming_completed": "notify_warming_completed",
    "system_health": "notify_system_health",
    "flood_rate_threshold": "notify_flood_rate_threshold",
}

DEDUP_TTL_SECONDS = 3600


class NotificationService:
    """Send notifications to Telegram chats via Bot API."""

    def __init__(self, bot_token: str) -> None:
        self.bot_token = bot_token
        self.api_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    async def send(self, event_type: str, message: str) -> None:
        """Send *message* to all admins subscribed to *event_type*."""
        field_name = EVENT_TYPE_FIELD_MAP.get(event_type)
        if field_name is None:
            logger.warning("Unknown notification event_type: %s", event_type)
            return

        with SessionLocal() as db:
            settings_list = (
                db.query(AdminNotificationSetting)
                .filter(AdminNotificationSetting.is_active.is_(True))
                .all()
            )

        content_hash = hashlib.md5(message.encode()).hexdigest()[:8]  # noqa: S324

        async with httpx.AsyncClient() as client:
            for setting in settings_list:
                if not getattr(setting, field_name, False):
                    continue

                chat_id = setting.chat_id
                dedup_key = f"notif_dedup:{chat_id}:{event_type}:{content_hash}"

                redis = get_sync_redis()
                if redis is not None:
                    if redis.get(dedup_key):
                        logger.debug(
                            "Skipping duplicate notification %s for chat %s",
                            event_type,
                            chat_id,
                        )
                        continue

                payload = {
                    "chat_id": chat_id,
                    "text": message,
                    "parse_mode": "HTML",
                }
                try:
                    resp = await client.post(self.api_url, json=payload, timeout=10)
                    resp.raise_for_status()
                    logger.info(
                        "Notification sent: %s -> chat %s", event_type, chat_id
                    )
                    if redis is not None:
                        redis.set(dedup_key, "1", ex=DEDUP_TTL_SECONDS)
                except Exception:
                    logger.exception(
                        "Failed to send notification %s to chat %s",
                        event_type,
                        chat_id,
                    )


def send_notification_sync(event_type: str, message: str) -> None:
    """Call from Celery tasks (sync context)."""
    import asyncio

    from app.core.settings import get_settings

    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    service = NotificationService(settings.telegram_bot_token)
    asyncio.run(service.send(event_type, message))
