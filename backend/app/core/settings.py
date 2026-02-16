import logging
from functools import lru_cache
import json
from typing import List
from urllib.parse import urlparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "FreeCRM Inviter API"
    environment: str = "development"
    production: bool = False
    api_v1_prefix: str = "/api/v1"

    cors_origins: List[str] | str = Field(default_factory=list)
    cors_allow_credentials: bool = True

    database_url: str = "mysql+pymysql://rovena:rovena@db:3306/rovena"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str = "change-me"
    jwt_algorithm: str = "HS256"
    jwt_expiration_minutes: int = 15
    jwt_refresh_expiration_days: int = 30
    csrf_token: str = ""
    csrf_enabled: bool = False
    cache_ttl_seconds: int = 60

    telegram_bot_token: str = ""
    # TODO: убрать после полной миграции на per-account api_id (telegram_api_apps)
    # Сейчас используется как fallback для legacy Account модели
    telegram_api_id: int = 0
    telegram_api_hash: str = ""
    telegram_client_enabled: bool | None = None
    telegram_auth_ttl_seconds: int = 300
    session_enc_key: str = ""
    auth_flow_ttl_seconds: int = 300
    auth_flow_max_attempts: int = 5
    sentry_dsn: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    web_base_url: str = "http://localhost:5173"

    admin_user_id: int | None = None
    admin_telegram_id: int | None = None
    admin_email: str = ""

    app_role: str = "backend"
    dev_allow_localhost: bool = False

    proxy_config_path: str = "/app/3proxy.cfg"
    proxy_base_port: int = 10000
    proxy_reload_cmd: str = ""
    health_check_timeout_seconds: float = 2.0
    health_queue_warn_threshold: int = 100

    ws_broadcast_concurrency: int = 100

    @field_validator("telegram_api_id", mode="before")
    @classmethod
    def coerce_telegram_api_id(cls, v: object) -> int:
        if v is None or (isinstance(v, str) and not v.strip()):
            return 0
        return int(v)

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: object) -> List[str]:
        if value is None:
            return []
        if isinstance(value, list):
            return [str(origin).strip() for origin in value if str(origin).strip()]
        if isinstance(value, str):
            raw = value.strip()
            if not raw:
                return []
            try:
                parsed = json.loads(raw)
            except json.JSONDecodeError:
                return [origin.strip() for origin in raw.split(",") if origin.strip()]
            if isinstance(parsed, list):
                return [str(origin).strip() for origin in parsed if str(origin).strip()]
            if isinstance(parsed, str):
                return [parsed.strip()] if parsed.strip() else []
        return []

    @field_validator("api_v1_prefix", mode="before")
    @classmethod
    def normalize_api_v1_prefix(cls, value: object) -> str:
        if value is None:
            return "/api/v1"
        if isinstance(value, str):
            cleaned = value.strip() or "/api/v1"
            if not cleaned.startswith("/"):
                cleaned = f"/{cleaned}"
            if cleaned != "/" and cleaned.endswith("/"):
                cleaned = cleaned.rstrip("/")
            return cleaned
        return "/api/v1"


def _is_localhost(url: str) -> bool:
    """Return True if *url* points to a localhost address."""
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return False
    return hostname in ("localhost", "127.0.0.1", "0.0.0.0", "::1")


def validate_settings(settings: Settings) -> None:
    """Production preflight checks.

    In production mode — raises ``ValueError`` on misconfiguration.
    In development mode — logs warnings but never blocks startup.
    """
    errors: list[str] = []

    if settings.production:
        # Browser-facing checks only apply to the HTTP backend role.
        # Workers and cron containers never serve browsers, so
        # CORS_ORIGINS / WEB_BASE_URL are irrelevant for them.
        _needs_browser_checks = settings.app_role not in ("worker", "cron")

        if _needs_browser_checks:
            # -- CORS_ORIGINS --
            if not settings.cors_origins:
                errors.append(
                    "CORS_ORIGINS is empty. "
                    "Set it to your frontend domain(s), e.g. "
                    f'CORS_ORIGINS=\'["{settings.web_base_url}"]\'.'
                )
            elif settings.cors_origins == ["*"] or "*" in settings.cors_origins:
                errors.append(
                    "CORS_ORIGINS contains wildcard '*'. "
                    "Wildcard is not allowed in production — specify exact origin(s)."
                )

            # -- WEB_BASE_URL --
            if not settings.web_base_url:
                errors.append(
                    "WEB_BASE_URL is empty. "
                    "Set it to your Telegram Mini App URL, e.g. "
                    "WEB_BASE_URL=https://kass.freestorms.top"
                )
            elif settings.cors_origins and settings.web_base_url not in settings.cors_origins:
                errors.append(
                    f"WEB_BASE_URL={settings.web_base_url!r} is not listed in "
                    f"CORS_ORIGINS={settings.cors_origins!r}. "
                    "The frontend origin must be in the allowed list."
                )

            # -- Localhost in production --
            if not settings.dev_allow_localhost:
                localhost_origins = [o for o in (settings.cors_origins or []) if _is_localhost(o)]
                if localhost_origins:
                    errors.append(
                        f"CORS_ORIGINS contains localhost URL(s): {localhost_origins}. "
                        "Remove them or set DEV_ALLOW_LOCALHOST=true to override."
                    )
                if settings.web_base_url and _is_localhost(settings.web_base_url):
                    errors.append(
                        f"WEB_BASE_URL={settings.web_base_url!r} points to localhost. "
                        "Set a real domain or DEV_ALLOW_LOCALHOST=true to override."
                    )

        # -- TELEGRAM_AUTH_TTL_SECONDS --
        if settings.telegram_auth_ttl_seconds <= 0:
            errors.append(
                "TELEGRAM_AUTH_TTL_SECONDS must be > 0 in production "
                "(replay protection). Recommended: 300."
            )

        # -- ADMIN_TELEGRAM_ID (if admin bootstrap is intended) --
        if settings.admin_telegram_id is not None:
            if not isinstance(settings.admin_telegram_id, int):
                errors.append(
                    f"ADMIN_TELEGRAM_ID={settings.admin_telegram_id!r} "
                    "must be a numeric Telegram user ID."
                )

        if errors:
            msg = "Production preflight failed:\n  • " + "\n  • ".join(errors)
            raise ValueError(msg)

    else:
        # Development mode — warn but don't block
        if settings.cors_origins and "*" in settings.cors_origins:
            logger.warning(
                "CORS_ORIGINS contains wildcard '*' — acceptable in development only."
            )
        if settings.telegram_auth_ttl_seconds <= 0:
            logger.warning(
                "TELEGRAM_AUTH_TTL_SECONDS=%d — initData replay protection "
                "disabled. This is acceptable for local development only.",
                settings.telegram_auth_ttl_seconds,
            )

    # Log effective config (no secrets)
    logger.info(
        "Effective config | ENVIRONMENT=%s | WEB_BASE_URL=%s | "
        "CORS_ORIGINS=%s | TELEGRAM_AUTH_TTL_SECONDS=%d | "
        "admin_id_present=%s | SESSION_ENC_KEY_set=%s",
        settings.environment,
        settings.web_base_url,
        settings.cors_origins,
        settings.telegram_auth_ttl_seconds,
        settings.admin_telegram_id is not None,
        bool(settings.session_enc_key),
    )


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.telegram_client_enabled is None:
        settings.telegram_client_enabled = bool(settings.telegram_api_id and settings.telegram_api_hash)
    # Reject empty/whitespace-only JWT_SECRET in ALL environments —
    # an empty HS256 secret lets anyone forge tokens.
    if not settings.jwt_secret or not settings.jwt_secret.strip():
        raise ValueError(
            "JWT_SECRET must not be empty. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )
    # In production, also require minimum length and reject the default value.
    if settings.production and (
        settings.jwt_secret == "change-me" or len(settings.jwt_secret) < 16
    ):
        raise ValueError(
            "JWT_SECRET must be at least 16 characters and not the default value. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(32))'"
        )

    if settings.production:
        if settings.database_url == "mysql+pymysql://rovena:rovena@db:3306/rovena":
            raise ValueError("Change DATABASE_URL!")
        if settings.telegram_client_enabled and (not settings.telegram_api_id or not settings.telegram_api_hash):
            raise ValueError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH!")
        if settings.telegram_client_enabled and not settings.session_enc_key:
            raise ValueError(
                "SESSION_ENC_KEY must be set in production when Telegram client is enabled. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if settings.stripe_secret_key or settings.stripe_webhook_secret:
            if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
                raise ValueError("Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET!")

        # Full preflight validation (CORS, WEB_BASE_URL, TTL, admin, localhost)
        validate_settings(settings)

        settings.cors_origins = settings.cors_origins or []
    else:
        # Development preflight (warnings only)
        validate_settings(settings)
        settings.cors_origins = ["*"]

    settings.cors_allow_credentials = bool(settings.cors_origins) and settings.cors_origins != ["*"]
    return settings
