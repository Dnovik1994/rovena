import json
import logging
import time
from typing import Any

import aioredis
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, class_=Session, autoflush=False, autocommit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


_local_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_redis_client: aioredis.Redis | None = None


def _now() -> float:
    return time.monotonic()


def _get_local_cache(key: str) -> dict[str, Any] | None:
    cached = _local_cache.get(key)
    if not cached:
        return None
    expires_at, payload = cached
    if expires_at < _now():
        _local_cache.pop(key, None)
        return None
    return payload


def _set_local_cache(key: str, payload: dict[str, Any], ttl: int) -> None:
    _local_cache[key] = (_now() + ttl, payload)


def clear_local_cache() -> None:
    _local_cache.clear()


async def _get_async_redis() -> aioredis.Redis | None:
    global _redis_client
    if not settings.redis_url:
        return None
    if _redis_client is None:
        _redis_client = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def _get_cached_payload(key: str) -> dict[str, Any] | None:
    payload = _get_local_cache(key)
    if payload:
        return payload
    redis_client = await _get_async_redis()
    if not redis_client:
        return None
    try:
        cached = await redis_client.get(key)
    except Exception:  # noqa: BLE001
        return None
    if not cached:
        return None
    try:
        data = json.loads(cached)
    except json.JSONDecodeError:
        return None
    _set_local_cache(key, data, settings.cache_ttl_seconds)
    return data


async def _set_cached_payload(key: str, payload: dict[str, Any]) -> None:
    _set_local_cache(key, payload, settings.cache_ttl_seconds)
    redis_client = await _get_async_redis()
    if not redis_client:
        return
    try:
        await redis_client.setex(key, settings.cache_ttl_seconds, json.dumps(payload))
    except Exception:  # noqa: BLE001
        return


async def get_cached_user(db: Session, user_id: int):
    from app.models.user import User

    cache_key = f"user:{user_id}"
    cached = await _get_cached_payload(cache_key)
    if cached:
        logger.info("Cache hit for user", extra={"user_id": user_id})
        role_value = cached.get("role")
        if role_value:
            from app.models.user import UserRole

            cached["role"] = UserRole(role_value)
        return User(**cached)

    user = db.get(User, user_id)
    if not user:
        return None
    payload = {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "role": user.role.value if getattr(user, "role", None) else None,
        "tariff_id": user.tariff_id,
    }
    await _set_cached_payload(cache_key, payload)
    return user


async def get_cached_tariff(db: Session, tariff_id: int):
    from app.models.tariff import Tariff

    cache_key = f"tariff:{tariff_id}"
    cached = await _get_cached_payload(cache_key)
    if cached:
        logger.info("Cache hit for tariff", extra={"tariff_id": tariff_id})
        return Tariff(**cached)

    tariff = db.get(Tariff, tariff_id)
    if not tariff:
        return None
    payload = {
        "id": tariff.id,
        "name": tariff.name,
        "max_accounts": tariff.max_accounts,
        "max_invites_day": tariff.max_invites_day,
        "price": tariff.price,
    }
    await _set_cached_payload(cache_key, payload)
    return tariff
