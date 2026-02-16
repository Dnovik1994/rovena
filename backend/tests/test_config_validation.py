"""Tests for production preflight / validate_settings().

This file uses conftest fixtures (db_engine, etc.) but only needs
Settings and validate_settings from settings.py. The conftest is
loaded automatically by pytest.
"""

import logging
import os
import sys
from pathlib import Path

import pytest

# Ensure backend is on sys.path (same as conftest.py does)
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

# Set env defaults so Settings() can be instantiated without .env
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "")
os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("PRODUCTION", "false")

from app.core.settings import Settings, get_settings, validate_settings  # noqa: E402


def _make_settings(overrides: dict) -> Settings:
    """Build a Settings instance with sensible production defaults, then apply overrides."""
    defaults = {
        "production": True,
        "environment": "production",
        "cors_origins": ["https://kass.freestorms.top"],
        "web_base_url": "https://kass.freestorms.top",
        "telegram_auth_ttl_seconds": 300,
        "jwt_secret": "real-production-secret",
        "database_url": "mysql+pymysql://prod:prod@db:3306/prod",
        "admin_telegram_id": None,
        "dev_allow_localhost": False,
    }
    defaults.update(overrides)
    return Settings(**defaults)


# ── Production failures ──────────────────────────────────────────────


class TestProductionFails:
    def test_wildcard_cors_rejected(self):
        settings = _make_settings({"cors_origins": ["*"]})
        with pytest.raises(ValueError, match="wildcard"):
            validate_settings(settings)

    def test_wildcard_among_origins_rejected(self):
        settings = _make_settings(
            {"cors_origins": ["https://kass.freestorms.top", "*"]}
        )
        with pytest.raises(ValueError, match="wildcard"):
            validate_settings(settings)

    def test_empty_cors_rejected(self):
        settings = _make_settings({"cors_origins": []})
        with pytest.raises(ValueError, match="CORS_ORIGINS is empty"):
            validate_settings(settings)

    def test_empty_web_base_url_rejected(self):
        settings = _make_settings({"web_base_url": ""})
        with pytest.raises(ValueError, match="WEB_BASE_URL is empty"):
            validate_settings(settings)

    def test_web_base_url_not_in_cors(self):
        settings = _make_settings(
            {
                "web_base_url": "https://other.example.com",
                "cors_origins": ["https://kass.freestorms.top"],
            }
        )
        with pytest.raises(ValueError, match="not listed in CORS_ORIGINS"):
            validate_settings(settings)

    def test_ttl_zero_rejected(self):
        settings = _make_settings({"telegram_auth_ttl_seconds": 0})
        with pytest.raises(ValueError, match="TELEGRAM_AUTH_TTL_SECONDS"):
            validate_settings(settings)

    def test_ttl_negative_rejected(self):
        settings = _make_settings({"telegram_auth_ttl_seconds": -1})
        with pytest.raises(ValueError, match="TELEGRAM_AUTH_TTL_SECONDS"):
            validate_settings(settings)

    def test_localhost_cors_rejected(self):
        settings = _make_settings(
            {
                "cors_origins": ["http://localhost:5173"],
                "web_base_url": "http://localhost:5173",
            }
        )
        with pytest.raises(ValueError, match="localhost"):
            validate_settings(settings)

    def test_localhost_web_base_url_rejected(self):
        settings = _make_settings(
            {
                "web_base_url": "http://localhost:5173",
                "cors_origins": ["http://localhost:5173"],
            }
        )
        with pytest.raises(ValueError, match="localhost"):
            validate_settings(settings)

    def test_localhost_allowed_with_flag(self):
        """DEV_ALLOW_LOCALHOST=true suppresses localhost rejection."""
        settings = _make_settings(
            {
                "cors_origins": ["http://localhost:5173"],
                "web_base_url": "http://localhost:5173",
                "dev_allow_localhost": True,
            }
        )
        # Should not raise
        validate_settings(settings)

    def test_multiple_errors_collected(self):
        """All errors are reported at once, not just the first one."""
        settings = _make_settings(
            {
                "cors_origins": [],
                "web_base_url": "",
                "telegram_auth_ttl_seconds": 0,
            }
        )
        with pytest.raises(ValueError, match="CORS_ORIGINS is empty") as exc_info:
            validate_settings(settings)
        msg = str(exc_info.value)
        assert "WEB_BASE_URL is empty" in msg
        assert "TELEGRAM_AUTH_TTL_SECONDS" in msg


# ── Production success ───────────────────────────────────────────────


class TestProductionPasses:
    def test_valid_config(self):
        settings = _make_settings({})
        # Should not raise
        validate_settings(settings)

    def test_valid_config_with_admin(self):
        settings = _make_settings({"admin_telegram_id": 123456789})
        validate_settings(settings)


# ── Development mode (warns, does not fail) ──────────────────────────


class TestDevelopmentWarns:
    def test_wildcard_cors_warns(self, caplog):
        settings = _make_settings(
            {
                "production": False,
                "cors_origins": ["*"],
            }
        )
        with caplog.at_level(logging.WARNING):
            validate_settings(settings)
        assert "wildcard" in caplog.text.lower()

    def test_ttl_zero_warns(self, caplog):
        settings = _make_settings(
            {
                "production": False,
                "telegram_auth_ttl_seconds": 0,
            }
        )
        with caplog.at_level(logging.WARNING):
            validate_settings(settings)
        assert "TELEGRAM_AUTH_TTL_SECONDS" in caplog.text

    def test_dev_does_not_raise_on_bad_config(self, caplog):
        """In development, even a bad config only warns."""
        settings = _make_settings(
            {
                "production": False,
                "cors_origins": ["*"],
                "web_base_url": "",
                "telegram_auth_ttl_seconds": 0,
            }
        )
        with caplog.at_level(logging.WARNING):
            validate_settings(settings)  # must not raise


# ── Worker role skips browser checks ──────────────────────────────


class TestWorkerRoleSkipsBrowserChecks:
    """Workers don't serve browsers, so CORS / WEB_BASE_URL checks are irrelevant."""

    def test_worker_ignores_empty_cors(self):
        settings = _make_settings({"app_role": "worker", "cors_origins": []})
        validate_settings(settings)  # must not raise

    def test_worker_ignores_localhost_web_base_url(self):
        settings = _make_settings(
            {
                "app_role": "worker",
                "web_base_url": "http://localhost:5173",
                "cors_origins": ["http://localhost:5173"],
            }
        )
        validate_settings(settings)  # must not raise

    def test_worker_still_checks_ttl(self):
        settings = _make_settings(
            {"app_role": "worker", "telegram_auth_ttl_seconds": 0}
        )
        with pytest.raises(ValueError, match="TELEGRAM_AUTH_TTL_SECONDS"):
            validate_settings(settings)

    def test_cron_ignores_empty_cors(self):
        settings = _make_settings({"app_role": "cron", "cors_origins": []})
        validate_settings(settings)  # must not raise


# ── JWT_SECRET validation (get_settings) ─────────────────────────


class TestJwtSecretValidation:
    """JWT_SECRET must not be empty in any env, and must be ≥16 chars in production."""

    def _setup_prod_env(self, monkeypatch):
        """Set minimal env vars for a valid production config."""
        monkeypatch.setenv("PRODUCTION", "true")
        monkeypatch.setenv("DATABASE_URL", "mysql+pymysql://u:p@host:3306/db")
        monkeypatch.setenv("CORS_ORIGINS", '["https://example.com"]')
        monkeypatch.setenv("WEB_BASE_URL", "https://example.com")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")

    def test_empty_jwt_secret_rejected_in_dev(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "false")
        monkeypatch.setenv("JWT_SECRET", "")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="JWT_SECRET must not be empty"):
            get_settings()

    def test_whitespace_jwt_secret_rejected_in_dev(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "false")
        monkeypatch.setenv("JWT_SECRET", "   ")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="JWT_SECRET must not be empty"):
            get_settings()

    def test_empty_jwt_secret_rejected_in_production(self, monkeypatch):
        get_settings.cache_clear()
        self._setup_prod_env(monkeypatch)
        monkeypatch.setenv("JWT_SECRET", "")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="JWT_SECRET must not be empty"):
            get_settings()

    def test_short_jwt_secret_rejected_in_production(self, monkeypatch):
        get_settings.cache_clear()
        self._setup_prod_env(monkeypatch)
        monkeypatch.setenv("JWT_SECRET", "too-short")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="at least 16 characters"):
            get_settings()

    def test_change_me_rejected_in_production(self, monkeypatch):
        get_settings.cache_clear()
        self._setup_prod_env(monkeypatch)
        monkeypatch.setenv("JWT_SECRET", "change-me")
        get_settings.cache_clear()
        with pytest.raises(ValueError, match="at least 16 characters"):
            get_settings()

    def test_valid_jwt_secret_accepted_in_production(self, monkeypatch):
        get_settings.cache_clear()
        self._setup_prod_env(monkeypatch)
        monkeypatch.setenv("JWT_SECRET", "prod-secret-value-long-enough")
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.jwt_secret == "prod-secret-value-long-enough"

    def test_short_jwt_secret_allowed_in_dev(self, monkeypatch):
        """In development, short (but non-empty) secrets are allowed."""
        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "false")
        monkeypatch.setenv("JWT_SECRET", "dev-secret")
        get_settings.cache_clear()
        settings = get_settings()
        assert settings.jwt_secret == "dev-secret"
