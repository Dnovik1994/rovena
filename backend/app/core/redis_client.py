"""Shared synchronous Redis client singleton.

Provides a module-level Redis connection reused across the application,
preventing connection leaks from repeated ``Redis.from_url()`` calls.

The async counterpart lives in :mod:`app.core.cache`.
"""

from __future__ import annotations

import logging

from redis import Redis

from app.core.settings import get_settings

logger = logging.getLogger(__name__)

_client: Redis | None = None
_client_decoded: Redis | None = None


def get_sync_redis() -> Redis | None:
    """Return a shared sync Redis client (bytes mode)."""
    global _client
    settings = get_settings()
    if not settings.redis_url:
        return None
    if _client is None:
        _client = Redis.from_url(settings.redis_url)
    return _client


def get_sync_redis_decoded() -> Redis | None:
    """Return a shared sync Redis client with ``decode_responses=True``."""
    global _client_decoded
    settings = get_settings()
    if not settings.redis_url:
        return None
    if _client_decoded is None:
        _client_decoded = Redis.from_url(settings.redis_url, decode_responses=True)
    return _client_decoded


def close_sync_redis() -> None:
    """Close all shared sync Redis clients. Call on application shutdown."""
    global _client, _client_decoded
    for c in (_client, _client_decoded):
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                logger.exception("Error closing sync Redis client")
    _client = None
    _client_decoded = None
