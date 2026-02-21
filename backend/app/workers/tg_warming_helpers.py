"""Helpers for TelegramAccount warming tasks."""

from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.settings import get_settings


def is_quiet_hours() -> bool:
    """Проверяет тихие часы по настройкам."""
    settings = get_settings()
    tz = ZoneInfo(settings.warming_timezone)
    current_hour = datetime.now(tz).hour
    return settings.warming_quiet_hours_start <= current_hour < settings.warming_quiet_hours_end
