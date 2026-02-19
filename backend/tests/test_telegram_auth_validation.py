"""Tests for Telegram initData canonicalization and HMAC validation.

Covers:
- Normal valid initData validation
- Duplicate-key rejection (policy: reject as parse_failed)
- Proper sort-based data_check_string construction
- TTL enforcement
"""

from __future__ import annotations

import hashlib
import hmac
import time
from urllib.parse import urlencode

import pytest

from app.services.telegram_auth import (
    TelegramAuthError,
    _build_data_check_string,
    _parse_init_data_pairs,
    validate_init_data,
)


# ─── Helpers ──────────────────────────────────────────────────────────


def _make_init_data(
    params: list[tuple[str, str]],
    bot_token: str = "test-bot-token",
) -> str:
    """Build a valid initData string with correct HMAC hash."""
    # Sort data pairs by key (per spec) and build data_check_string
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

    # Build query string preserving order, append hash at end
    all_pairs = data_pairs + [("hash", hash_value)]
    return urlencode(all_pairs)


# ─── _parse_init_data_pairs ──────────────────────────────────────────


class TestParseInitDataPairs:
    def test_normal_parsing(self):
        raw = "auth_date=123&user=%7B%7D&hash=abcdef01"
        pairs, hash_val = _parse_init_data_pairs(raw)
        assert hash_val == "abcdef01"
        assert ("auth_date", "123") in pairs
        assert ("user", "{}") in pairs
        # hash should not be in data_pairs
        assert all(k != "hash" for k, _ in pairs)

    def test_missing_hash_raises(self):
        raw = "auth_date=123&user=%7B%7D"
        with pytest.raises(TelegramAuthError, match="Missing hash"):
            _parse_init_data_pairs(raw)

    def test_duplicate_keys_rejected(self):
        """Duplicate keys in initData should be rejected (parse_failed).

        Policy: Telegram spec does not define duplicate keys. Duplicates
        may indicate parameter injection, so we reject them outright.
        """
        raw = "auth_date=123&auth_date=456&hash=abcdef01"
        with pytest.raises(TelegramAuthError, match="Duplicate keys") as exc_info:
            _parse_init_data_pairs(raw)
        assert exc_info.value.reason_code == "parse_failed"

    def test_empty_init_data_raises(self):
        with pytest.raises(TelegramAuthError, match="Missing hash"):
            _parse_init_data_pairs("")


# ─── _build_data_check_string ────────────────────────────────────────


class TestBuildDataCheckString:
    def test_sorts_by_key(self):
        pairs = [("user", "{}"), ("auth_date", "123"), ("query_id", "qid")]
        result = _build_data_check_string(pairs)
        assert result == "auth_date=123\nquery_id=qid\nuser={}"

    def test_single_pair(self):
        pairs = [("auth_date", "100")]
        assert _build_data_check_string(pairs) == "auth_date=100"

    def test_empty_pairs(self):
        assert _build_data_check_string([]) == ""


# ─── validate_init_data (integration) ────────────────────────────────


class TestValidateInitData:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        monkeypatch.setenv("PRODUCTION", "false")
        yield
        get_settings.cache_clear()

    def test_valid_init_data(self):
        auth_date = str(int(time.time()))
        user_json = '{"id":123,"first_name":"Test"}'
        init_data = _make_init_data([
            ("auth_date", auth_date),
            ("user", user_json),
            ("query_id", "qid_test"),
        ])
        result = validate_init_data(init_data)
        assert result["auth_date"] == auth_date
        assert result["user"] == user_json
        assert result["query_id"] == "qid_test"
        # hash should not be in result
        assert "hash" not in result

    def test_tampered_data_rejected(self):
        auth_date = str(int(time.time()))
        init_data = _make_init_data([
            ("auth_date", auth_date),
            ("user", '{"id":123}'),
        ])
        # Tamper with the data
        init_data = init_data.replace(f"auth_date={auth_date}", "auth_date=999")
        with pytest.raises(TelegramAuthError, match="Invalid initData signature"):
            validate_init_data(init_data)

    def test_expired_init_data_rejected(self):
        old_time = str(int(time.time()) - 600)  # 10 min ago, TTL=300
        init_data = _make_init_data([
            ("auth_date", old_time),
            ("user", '{"id":123}'),
        ])
        with pytest.raises(TelegramAuthError, match="expired"):
            validate_init_data(init_data)

    def test_duplicate_key_rejected_in_full_validation(self):
        # Manually build a string with duplicate auth_date + valid hash
        # The duplicate check happens before HMAC, so hash doesn't matter
        raw = "auth_date=123&auth_date=456&user=%7B%7D&hash=0000000011111111"
        with pytest.raises(TelegramAuthError, match="Duplicate keys"):
            validate_init_data(raw)

    def test_missing_init_data(self):
        with pytest.raises(TelegramAuthError, match="Missing initData"):
            validate_init_data("")

    def test_missing_bot_token(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
        get_settings.cache_clear()
        with pytest.raises(TelegramAuthError, match="not configured"):
            validate_init_data("auth_date=123&hash=abc")


# ─── TTL settings validation ─────────────────────────────────────────


class TestTTLSettingsValidation:
    def test_production_rejects_zero_ttl(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "true")
        monkeypatch.setenv("JWT_SECRET", "prod-secret-value-long-enough")
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@host:3306/db")
        monkeypatch.setenv("CORS_ORIGINS", '["https://example.com"]')
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "0")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="TELEGRAM_AUTH_TTL_SECONDS must be > 0"):
            get_settings()

    def test_production_rejects_negative_ttl(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "true")
        monkeypatch.setenv("JWT_SECRET", "prod-secret-value-long-enough")
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@host:3306/db")
        monkeypatch.setenv("CORS_ORIGINS", '["https://example.com"]')
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "-1")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="TELEGRAM_AUTH_TTL_SECONDS must be > 0"):
            get_settings()

    def test_production_accepts_positive_ttl(self, monkeypatch):
        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "true")
        monkeypatch.setenv("JWT_SECRET", "prod-secret-value-long-enough")
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@host:3306/db")
        monkeypatch.setenv("CORS_ORIGINS", '["https://example.com"]')
        monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.telegram_auth_ttl_seconds == 300

    def test_dev_allows_zero_ttl_with_warning(self, monkeypatch, caplog):
        import logging

        from app.core.settings import get_settings

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "false")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "0")
        get_settings.cache_clear()
        with caplog.at_level(logging.WARNING, logger="app.core.settings"):
            settings = get_settings()
        assert settings.telegram_auth_ttl_seconds == 0
        assert "replay protection disabled" in caplog.text.lower()

    def test_default_ttl_is_300(self, monkeypatch):
        from app.core.settings import Settings

        # Without setting the env var, default should be 300
        monkeypatch.delenv("TELEGRAM_AUTH_TTL_SECONDS", raising=False)
        s = Settings()
        assert s.telegram_auth_ttl_seconds == 300
