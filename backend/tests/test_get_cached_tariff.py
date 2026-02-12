"""Tests for get_cached_tariff — verifies no NameError and correct cache-miss behaviour."""

import pytest

from app.core import cache, database
from app.core.database import get_cached_tariff


class FakeRedis:
    """Minimal async Redis stub that always returns cache-miss."""

    def __init__(self):
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.store[key] = value

    async def delete(self, key: str):
        self.store.pop(key, None)


@pytest.mark.asyncio
async def test_get_cached_tariff_no_name_error(db_session, monkeypatch):
    """get_cached_tariff must not raise NameError (get_json is imported)."""
    fake = FakeRedis()

    async def fake_client():
        return fake

    monkeypatch.setattr(cache, "_get_redis_client", fake_client)

    # tariff_id=1 exists (seeded by conftest)
    tariff = await get_cached_tariff(db_session, 1)
    assert tariff is not None
    assert tariff.name == "Free"


@pytest.mark.asyncio
async def test_get_cached_tariff_cache_miss_returns_from_db(db_session, monkeypatch):
    """On cache miss, tariff is fetched from DB and cached."""
    fake = FakeRedis()

    async def fake_client():
        return fake

    monkeypatch.setattr(cache, "_get_redis_client", fake_client)

    tariff = await get_cached_tariff(db_session, 2)
    assert tariff is not None
    assert tariff.name == "Pro"

    # Verify the value was cached
    assert "tariff:2" in fake.store


@pytest.mark.asyncio
async def test_get_cached_tariff_missing_tariff(db_session, monkeypatch):
    """Non-existent tariff_id returns None."""
    fake = FakeRedis()

    async def fake_client():
        return fake

    monkeypatch.setattr(cache, "_get_redis_client", fake_client)

    result = await get_cached_tariff(db_session, 9999)
    assert result is None


@pytest.mark.asyncio
async def test_get_cached_tariff_no_redis(db_session, monkeypatch):
    """When Redis is unavailable (returns None), still fetches from DB."""

    async def no_redis():
        return None

    monkeypatch.setattr(cache, "_get_redis_client", no_redis)

    tariff = await get_cached_tariff(db_session, 1)
    assert tariff is not None
    assert tariff.name == "Free"
