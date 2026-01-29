import hashlib
import hmac
import time
from typing import Any
from urllib.parse import parse_qsl

from app.core.settings import get_settings


class TelegramAuthError(ValueError):
    pass


def _build_data_check_string(data: dict[str, Any]) -> str:
    items = [f"{key}={value}" for key, value in sorted(data.items())]
    return "\n".join(items)


def validate_init_data(init_data: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise TelegramAuthError("Telegram bot token is not configured")

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as exc:
        raise TelegramAuthError("Malformed initData") from exc
    hash_value = parsed.pop("hash", None)
    if not hash_value:
        raise TelegramAuthError("Missing hash in initData")

    data_check_string = _build_data_check_string(parsed)
    secret_key = hashlib.sha256(settings.telegram_bot_token.encode("utf-8")).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, hash_value):
        raise TelegramAuthError("Invalid initData signature")

    if settings.telegram_auth_ttl_seconds > 0:
        auth_date_raw = parsed.get("auth_date")
        if not auth_date_raw:
            raise TelegramAuthError("Missing auth_date in initData")
        try:
            auth_date = int(auth_date_raw)
        except ValueError as exc:
            raise TelegramAuthError("Invalid auth_date in initData") from exc
        now = int(time.time())
        if auth_date > now + 60:
            raise TelegramAuthError("auth_date is in the future")
        if now - auth_date > settings.telegram_auth_ttl_seconds:
            raise TelegramAuthError("initData is expired")

    return parsed
