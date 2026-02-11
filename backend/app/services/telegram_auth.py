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


def _parse_init_data_pairs(init_data: str) -> tuple[list[tuple[str, str]], str]:
    """Parse initData into (data_pairs, hash_value).

    Uses parse_qsl to preserve all key-value pairs (no dict() dedup).
    Rejects initData with duplicate keys — Telegram spec does not define
    them, so duplicates indicate tampering or a malformed payload.
    """
    try:
        pairs = parse_qsl(init_data, strict_parsing=True)
    except ValueError as exc:
        raise TelegramAuthError("Malformed initData", "parse_failed") from exc

    hash_value: str | None = None
    data_pairs: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "hash":
            hash_value = value
        else:
            data_pairs.append((key, value))

    if not hash_value:
        raise TelegramAuthError("Missing hash in initData", "missing_hash")

    # Reject duplicate keys (policy: duplicates are not part of the Telegram
    # spec and may indicate parameter injection).
    seen_keys = [k for k, _ in data_pairs]
    if len(seen_keys) != len(set(seen_keys)):
        raise TelegramAuthError(
            "Duplicate keys in initData",
            "parse_failed",
            hash_prefix=hash_value[:8],
        )

    return data_pairs, hash_value


def _build_data_check_string(pairs: list[tuple[str, str]]) -> str:
    """Build data_check_string per Telegram spec: sort by key, join with \\n."""
    sorted_pairs = sorted(pairs, key=lambda p: p[0])
    return "\n".join(f"{key}={value}" for key, value in sorted_pairs)


def validate_init_data(init_data: str) -> dict[str, Any]:
    settings = get_settings()
    if not settings.telegram_bot_token:
        raise TelegramAuthError(
            "Telegram bot token is not configured",
            "hmac_mismatch",
        )
    if not init_data:
        raise TelegramAuthError("Missing initData", "missing_init_data")

    data_pairs, hash_value = _parse_init_data_pairs(init_data)
    hash_prefix = hash_value[:8]

    data_check_string = _build_data_check_string(data_pairs)
    # Telegram WebApp signature algorithm:
    #   1) secret_key = HMAC_SHA256(key="WebAppData", msg=bot_token)
    #   2) hash = HMAC_SHA256(key=secret_key, msg=data_check_string)
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=settings.telegram_bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, hash_value):
        raise TelegramAuthError(
            "Invalid initData signature",
            "hmac_mismatch",
            hash_prefix=hash_prefix,
        )

    parsed = dict(data_pairs)

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
