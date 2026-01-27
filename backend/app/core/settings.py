from functools import lru_cache
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "FreeCRM Inviter API"
    environment: str = "development"
    production: bool = False
    api_v1_prefix: str = "/api/v1"

    cors_origins: List[str] = Field(default_factory=list)

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
    sentry_dsn: str = ""
    stripe_secret_key: str = ""
    stripe_webhook_secret: str = ""
    web_base_url: str = "http://localhost:5173"

    proxy_config_path: str = "/app/3proxy.cfg"
    proxy_base_port: int = 10000
    proxy_reload_cmd: str = ""


@lru_cache

def get_settings() -> Settings:
    return Settings()
