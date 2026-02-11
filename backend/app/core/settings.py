import logging
from functools import lru_cache
import json
from typing import List

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
    telegram_api_id: str = ""
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

    proxy_config_path: str = "/app/3proxy.cfg"
    proxy_base_port: int = 10000
    proxy_reload_cmd: str = ""
    health_check_timeout_seconds: float = 2.0
    health_queue_warn_threshold: int = 100

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


@lru_cache

def get_settings() -> Settings:
    settings = Settings()
    if settings.telegram_client_enabled is None:
        settings.telegram_client_enabled = bool(settings.telegram_api_id and settings.telegram_api_hash)
    if settings.production and settings.jwt_secret == "change-me":
        raise ValueError("Change JWT_SECRET!")

    if settings.production:
        if settings.database_url == "mysql+pymysql://rovena:rovena@db:3306/rovena":
            raise ValueError("Change DATABASE_URL!")
        if settings.telegram_client_enabled and (not settings.telegram_api_id or not settings.telegram_api_hash):
            raise ValueError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH!")
        if settings.stripe_secret_key or settings.stripe_webhook_secret:
            if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
                raise ValueError("Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET!")
        if settings.telegram_auth_ttl_seconds <= 0:
            raise ValueError(
                "TELEGRAM_AUTH_TTL_SECONDS must be > 0 in production "
                "(replay protection). Recommended: 300."
            )
        if not settings.cors_origins or settings.cors_origins == ["*"]:
            raise ValueError(
                "CORS_ORIGINS must include your frontend domain(s) in production. "
                f"Example: CORS_ORIGINS='[\"{settings.web_base_url}\"]'. "
                "Wildcard '*' is not allowed."
            )
        settings.cors_origins = settings.cors_origins or []
    else:
        if settings.telegram_auth_ttl_seconds <= 0:
            logger.warning(
                "TELEGRAM_AUTH_TTL_SECONDS=%d — initData replay protection "
                "disabled. This is acceptable for local development only.",
                settings.telegram_auth_ttl_seconds,
            )
        settings.cors_origins = ["*"]

    settings.cors_allow_credentials = bool(settings.cors_origins) and settings.cors_origins != ["*"]
    return settings
