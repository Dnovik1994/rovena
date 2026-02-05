import pytest

from app.core.settings import get_settings


def _load_settings(monkeypatch: pytest.MonkeyPatch, **env: str):
    keys = {
        "PRODUCTION",
        "JWT_SECRET",
        "DATABASE_URL",
        "CORS_ORIGINS",
        "STRIPE_ENABLED",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
        "TELEGRAM_AUTH_ENABLED",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CLIENT_ENABLED",
        "TELEGRAM_API_ID",
        "TELEGRAM_API_HASH",
        "CSRF_ENABLED",
        "CSRF_TOKEN",
        "SENTRY_ENABLED",
        "SENTRY_DSN",
    }
    for key in keys:
        if key not in env:
            monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    return get_settings()


def _base_prod_env():
    return {
        "PRODUCTION": "true",
        "JWT_SECRET": "test-secret",
        "DATABASE_URL": "postgresql://user:pass@localhost/db",
        "CORS_ORIGINS": '["https://example.com"]',
        "STRIPE_ENABLED": "false",
        "TELEGRAM_AUTH_ENABLED": "false",
        "TELEGRAM_CLIENT_ENABLED": "false",
        "CSRF_ENABLED": "false",
        "SENTRY_ENABLED": "false",
    }


def test_production_rejects_default_jwt_secret(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["JWT_SECRET"] = "change-me"
    with pytest.raises(ValueError, match="Change JWT_SECRET!"):
        _load_settings(monkeypatch, **env)


def test_production_rejects_default_database_url(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["DATABASE_URL"] = "mysql+pymysql://rovena:rovena@db:3306/rovena"
    with pytest.raises(ValueError, match="Change DATABASE_URL!"):
        _load_settings(monkeypatch, **env)


def test_production_requires_cors_origins(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["CORS_ORIGINS"] = '["*"]'
    with pytest.raises(ValueError, match="Set CORS_ORIGINS for production!"):
        _load_settings(monkeypatch, **env)


def test_stripe_enabled_requires_secrets(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["STRIPE_ENABLED"] = "true"
    with pytest.raises(ValueError, match="Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET!"):
        _load_settings(monkeypatch, **env)


def test_stripe_disabled_allows_missing_secrets(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    settings = _load_settings(monkeypatch, **env)
    assert settings.stripe_enabled is False


def test_telegram_client_disabled_allows_missing_keys(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    settings = _load_settings(monkeypatch, **env)
    assert settings.telegram_client_enabled is False


def test_telegram_client_enabled_requires_keys(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["TELEGRAM_CLIENT_ENABLED"] = "true"
    with pytest.raises(ValueError, match="Set TELEGRAM_API_ID and TELEGRAM_API_HASH!"):
        _load_settings(monkeypatch, **env)


def test_csrf_enabled_requires_token(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["CSRF_ENABLED"] = "true"
    with pytest.raises(ValueError, match="Set CSRF_TOKEN!"):
        _load_settings(monkeypatch, **env)


def test_sentry_enabled_requires_dsn(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["SENTRY_ENABLED"] = "true"
    with pytest.raises(ValueError, match="Set SENTRY_DSN!"):
        _load_settings(monkeypatch, **env)


def test_telegram_auth_enabled_requires_bot_token(monkeypatch: pytest.MonkeyPatch):
    env = _base_prod_env()
    env["TELEGRAM_AUTH_ENABLED"] = "true"
    with pytest.raises(ValueError, match="Set TELEGRAM_BOT_TOKEN!"):
        _load_settings(monkeypatch, **env)
