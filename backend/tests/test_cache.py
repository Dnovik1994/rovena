import pytest

from app.core import cache


class FakeRedis:
    def __init__(self):
        self.data: dict[str, str] = {}

    async def get(self, key: str):
        return self.data.get(key)

    async def setex(self, key: str, ttl: int, value: str):
        self.data[key] = value

    async def delete(self, key: str):
        self.data.pop(key, None)


@pytest.mark.asyncio
async def test_cache_set_get_delete(monkeypatch):
    fake = FakeRedis()

    async def fake_client():
        return fake

    monkeypatch.setattr(cache, "_get_redis_client", fake_client)
    await cache.set_json("key:1", {"value": 1}, ttl_seconds=60)
    assert await cache.get_json("key:1") == {"value": 1}
    await cache.delete_key("key:1")
    assert await cache.get_json("key:1") is None
