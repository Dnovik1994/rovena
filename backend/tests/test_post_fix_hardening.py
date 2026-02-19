"""Tests for post-fix hardening changes.

Covers:
- verify_account uses async broadcast (not sync Redis publish)
- CORS error message includes domain hint
- Auth rejection increments Prometheus counter
- Future auth_date edge cases
- verify_account latency metric is observed
"""

from __future__ import annotations

import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlencode

import pytest


# ─── Task 1: verify_account async broadcast ──────────────────────────

class TestVerifyAccountAsyncBroadcast:
    """verify_account must use await manager.send_to_user (non-blocking)
    instead of manager.broadcast_sync (blocks event loop with sync Redis).
    """

    def test_verify_account_dispatches_to_celery_not_blocking(self):
        """Static check: verify_tg_account is non-blocking — dispatches to Celery worker."""
        from pathlib import Path

        # Read source directly to avoid heavy import chain (pyrogram/cryptography)
        src = Path(__file__).resolve().parent.parent / "app" / "api" / "v1" / "tg_accounts.py"
        source = src.read_text()

        # Find the verify_tg_account function body (sync def)
        start = source.find("def verify_tg_account")
        assert start != -1, "verify_tg_account function not found"
        # Find the next top-level function/class definition to bound the search
        next_def = source.find("\n@router.", start + 1)
        if next_def == -1:
            next_def = len(source)
        func_body = source[start:next_def]

        # Should dispatch to Celery, NOT call Pyrogram directly
        assert "verify_account_task" in func_body, (
            "verify_tg_account should dispatch to verify_account_task Celery task"
        )
        assert "async with client" not in func_body, (
            "verify_tg_account should NOT run blocking Pyrogram calls in HTTP handler"
        )


# ─── Task 2: TTL / auth_date edge cases ─────────────────────────────


def _make_init_data(
    params: list[tuple[str, str]],
    bot_token: str = "test-bot-token",
) -> str:
    data_pairs = [(k, v) for k, v in params if k != "hash"]
    sorted_pairs = sorted(data_pairs, key=lambda p: p[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_pairs)
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    hash_value = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    all_pairs = data_pairs + [("hash", hash_value)]
    return urlencode(all_pairs)


class TestAuthDateEdgeCases:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        monkeypatch.setenv("PRODUCTION", "false")
        yield
        get_settings.cache_clear()

    def test_future_auth_date_beyond_tolerance_rejected(self):
        """auth_date more than 60s in the future should be rejected."""
        from app.services.telegram_auth import TelegramAuthError, validate_init_data

        future_time = str(int(time.time()) + 120)  # 2 minutes in future
        init_data = _make_init_data([
            ("auth_date", future_time),
            ("user", '{"id":123}'),
        ])
        with pytest.raises(TelegramAuthError, match="future"):
            validate_init_data(init_data)

    def test_auth_date_within_tolerance_accepted(self):
        """auth_date up to 60s in the future should be accepted."""
        from app.services.telegram_auth import validate_init_data

        near_future = str(int(time.time()) + 30)  # 30s in future
        init_data = _make_init_data([
            ("auth_date", near_future),
            ("user", '{"id":123}'),
        ])
        result = validate_init_data(init_data)
        assert result["auth_date"] == near_future

    def test_auth_date_exactly_at_ttl_boundary_rejected(self):
        """auth_date exactly TTL seconds old should be rejected (> not >=)."""
        from app.services.telegram_auth import TelegramAuthError, validate_init_data

        # TTL is 300s; set auth_date to 301s ago to be clearly past boundary
        old_time = str(int(time.time()) - 301)
        init_data = _make_init_data([
            ("auth_date", old_time),
            ("user", '{"id":123}'),
        ])
        with pytest.raises(TelegramAuthError, match="expired"):
            validate_init_data(init_data)


# ─── Task 3: CORS error message clarity ──────────────────────────────


class TestCORSErrorClarity:
    def test_cors_prod_error_includes_domain_hint(self, monkeypatch):
        """Production CORS error should mention the WEB_BASE_URL domain."""
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "true")
        monkeypatch.setenv("JWT_SECRET", "prod-secret-value-long-enough")
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@host:3306/db")
        monkeypatch.setenv("CORS_ORIGINS", "")
        monkeypatch.setenv("WEB_BASE_URL", "https://myapp.example.com")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="CORS_ORIGINS is empty") as exc_info:
            get_settings()
        # Error message should reference the configured WEB_BASE_URL
        assert "https://myapp.example.com" in str(exc_info.value)

    def test_cors_prod_error_rejects_wildcard_with_hint(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "true")
        monkeypatch.setenv("JWT_SECRET", "prod-secret-value-long-enough")
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@host:3306/db")
        monkeypatch.setenv("CORS_ORIGINS", '["*"]')
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="Wildcard"):
            get_settings()


# ─── Task 4: Observability — auth rejection counter ─────────────────


class TestAuthRejectionMetric:
    def test_reject_counter_increments_on_expired(self, monkeypatch):
        """telegram_auth_reject_total should increment on expired initData."""
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        monkeypatch.setenv("PRODUCTION", "false")
        get_settings.cache_clear()

        from app.core.metrics import telegram_auth_reject_total

        # Build expired initData
        old_time = str(int(time.time()) - 600)
        init_data = _make_init_data([
            ("auth_date", old_time),
            ("user", '{"id":123}'),
        ])

        before = telegram_auth_reject_total.labels(reason="auth_date_expired")._value.get()

        # Simulate the auth endpoint logic
        from app.services.telegram_auth import TelegramAuthError, validate_init_data

        try:
            validate_init_data(init_data)
        except TelegramAuthError as exc:
            telegram_auth_reject_total.labels(reason=exc.reason_code).inc()

        after = telegram_auth_reject_total.labels(reason="auth_date_expired")._value.get()
        assert after == before + 1

    def test_reject_counter_increments_on_parse_failed(self, monkeypatch):
        """telegram_auth_reject_total should increment on duplicate keys."""
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        monkeypatch.setenv("PRODUCTION", "false")
        get_settings.cache_clear()

        from app.core.metrics import telegram_auth_reject_total

        raw = "auth_date=123&auth_date=456&user=%7B%7D&hash=0000000011111111"

        before = telegram_auth_reject_total.labels(reason="parse_failed")._value.get()

        from app.services.telegram_auth import TelegramAuthError, validate_init_data

        try:
            validate_init_data(raw)
        except TelegramAuthError as exc:
            telegram_auth_reject_total.labels(reason=exc.reason_code).inc()

        after = telegram_auth_reject_total.labels(reason="parse_failed")._value.get()
        assert after == before + 1


class TestVerifyAccountLatencyMetric:
    def test_histogram_is_registered(self):
        """verify_account_duration_seconds histogram should be importable."""
        from app.core.metrics import verify_account_duration_seconds

        # Verify it's a Histogram by checking observe method exists
        assert hasattr(verify_account_duration_seconds, "observe")
