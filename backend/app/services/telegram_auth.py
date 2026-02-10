import hashlib
import hmac
import time
from typing import Any
from urllib.parse import parse_qsl

from app.core.settings import get_settings


class TelegramAuthError(ValueError):
    def __init__(
        self,
        message: str,
        reason_code: str,
        *,
        auth_date: int | None = None,
        hash_prefix: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.auth_date = auth_date
        self.hash_prefix = hash_prefix


def _build_data_check_string(data: dict[str, Any]) -> str:
    items = [f"{key}={value}" for key, value in sorted(data.items())]
    return "\n".join(items)


def validate_init_data(init_data: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise TelegramAuthError(
            "Telegram bot token is not configured",
            "hmac_mismatch",
        )
    if not init_data:
        raise TelegramAuthError("Missing initData", "missing_init_data")

    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=True))
    except ValueError as exc:
        raise TelegramAuthError("Malformed initData", "parse_failed") from exc
    hash_value = parsed.pop("hash", None)
    if not hash_value:
        raise TelegramAuthError("Missing hash in initData", "missing_hash")
    hash_prefix = hash_value[:8]

    data_check_string = _build_data_check_string(parsed)
    secret_key = hmac.new(
        b"WebAppData",
        settings.telegram_bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key, data_check_string.encode("utf-8"), hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, hash_value):
        raise TelegramAuthError(
            "Invalid initData signature",
            "hmac_mismatch",
            hash_prefix=hash_prefix,
        )

    if settings.telegram_auth_ttl_seconds > 0:
        auth_date_raw = parsed.get("auth_date")
        if not auth_date_raw:
            raise TelegramAuthError(
                "Missing auth_date in initData",
                "auth_date_expired",
                hash_prefix=hash_prefix,
            )
        try:
            auth_date = int(auth_date_raw)
        except ValueError as exc:
            raise TelegramAuthError(
                "Invalid auth_date in initData",
                "auth_date_expired",
                hash_prefix=hash_prefix,
            ) from exc
        now = int(time.time())
        if auth_date > now + 60:
            raise TelegramAuthError(
                "auth_date is in the future",
                "auth_date_expired",
                auth_date=auth_date,
                hash_prefix=hash_prefix,
            )
        if now - auth_date > settings.telegram_auth_ttl_seconds:
            raise TelegramAuthError(
                "initData is expired",
                "auth_date_expired",
                auth_date=auth_date,
                hash_prefix=hash_prefix,
            )

    return parsed
