import json
import logging
from functools import wraps
from typing import Any, Awaitable, Callable

import redis.asyncio as redis

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_redis_client: redis.Redis | None = None


async def _get_redis_client() -> redis.Redis | None:
    global _redis_client
    settings = get_settings()
    if not settings.redis_url:
        return None
    if _redis_client is None:
        _redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    return _redis_client


async def get_json(key: str) -> dict[str, Any] | None:
    client = await _get_redis_client()
    if not client:
        return None
    try:
        cached = await client.get(key)
    except Exception:  # noqa: BLE001
        logger.exception("Cache read failed for key %s", key)
        return None
    if not cached:
        logger.debug("Cache miss for key %s", key)
        return None
    try:
        payload = json.loads(cached)
    except json.JSONDecodeError:
        logger.debug("Cache miss for key %s", key)
        return None
    logger.debug("Cache hit for key %s", key)
    return payload


async def set_json(key: str, payload: dict[str, Any], ttl_seconds: int = 60) -> None:
    client = await _get_redis_client()
    if not client:
        return
    try:
        await client.setex(key, ttl_seconds, json.dumps(payload))
    except Exception:  # noqa: BLE001
        logger.exception("Cache write failed for key %s", key)


async def delete(key: str) -> None:
    client = await _get_redis_client()
    if not client:
        return
    try:
        await client.delete(key)
    except Exception:  # noqa: BLE001
        logger.exception("Cache delete failed for key %s", key)


async def ping() -> bool:
    client = await _get_redis_client()
    if not client:
        return False
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001
        logger.exception("Cache ping failed")
        return False


delete_key = delete


def cache(
    ttl_seconds: int = 60,
    key_builder: Callable[..., str | None] | None = None,
    serializer: Callable[[Any], dict[str, Any]] | None = None,
    deserializer: Callable[[dict[str, Any]], Any] | None = None,
    validator: Callable[[Any], bool] | None = None,
    on_hit: Callable[..., None] | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            key = key_builder(*args, **kwargs) if key_builder else None
            if key:
                cached = await get_json(key)
                if cached is not None:
                    value = deserializer(cached) if deserializer else cached
                    if validator and not validator(value):
                        value = None
                    else:
                        if on_hit:
                            on_hit(value, *args, **kwargs)
                        return value
            result = await func(*args, **kwargs)
            if key and result is not None:
                payload = serializer(result) if serializer else result
                await set_json(key, payload, ttl_seconds)
            return result

        return wrapper

    return decorator
