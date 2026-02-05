from functools import lru_cache
import json
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    telegram_auth_ttl_seconds: int = 0
    sentry_dsn: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    web_base_url: str = "http://localhost:5173"
    stripe_enabled: bool = False
    sentry_enabled: bool = False
    telegram_auth_enabled: bool = True
    telegram_client_enabled: bool = False

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


@lru_cache

def get_settings() -> Settings:
    settings = Settings()
    if settings.production and settings.jwt_secret == "change-me":
        raise ValueError("Change JWT_SECRET!")

    if settings.production:
        if settings.database_url == "mysql+pymysql://rovena:rovena@db:3306/rovena":
            raise ValueError("Change DATABASE_URL!")
        if settings.stripe_enabled:
            if not settings.stripe_secret_key or not settings.stripe_webhook_secret:
                raise ValueError("Set STRIPE_SECRET_KEY and STRIPE_WEBHOOK_SECRET!")
        if settings.telegram_auth_enabled and not settings.telegram_bot_token:
            raise ValueError("Set TELEGRAM_BOT_TOKEN!")
        if settings.telegram_client_enabled:
            if not settings.telegram_api_id or not settings.telegram_api_hash:
                raise ValueError("Set TELEGRAM_API_ID and TELEGRAM_API_HASH!")
        if settings.csrf_enabled and not settings.csrf_token:
            raise ValueError("Set CSRF_TOKEN!")
        if settings.sentry_enabled and not settings.sentry_dsn:
            raise ValueError("Set SENTRY_DSN!")
        if not settings.cors_origins or settings.cors_origins == ["*"]:
            raise ValueError("Set CORS_ORIGINS for production!")
        settings.cors_origins = settings.cors_origins or []
    else:
        settings.cors_origins = ["*"]

    settings.cors_allow_credentials = bool(settings.cors_origins) and settings.cors_origins != ["*"]
    return settings
