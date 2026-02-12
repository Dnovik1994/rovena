"""Tests for Telegram initData atomic replay protection.

Covers:
- First request with valid initData succeeds (key set in Redis).
- Second request with same initData rejected as replay (HTTP 401).
- Different initData strings are independent.
- After TTL expiry (simulated by clearing store), initData accepted again.
- Redis unavailable in dev mode → check skipped (request proceeds).
- Redis unavailable in production → fail-closed (HTTP 503).
- Redis error during SET → fail-closed in production.
- TTL ≤ 0 → check is skipped entirely.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch
from urllib.parse import urlencode

import pytest

from app.core.settings import get_settings


# ─── Helpers ──────────────────────────────────────────────────────────


class FakeRedis:
    """Minimal Redis stub that supports ``SET key value NX EX ttl``."""

    def __init__(self):
        self._store: dict[str, str] = {}

    def set(
        self,
        name: str,
        value: str,
        *,
        ex: int | None = None,
        nx: bool = False,
    ) -> bool | None:
        if nx and name in self._store:
            return False
        self._store[name] = value
        return True


class ErrorRedis:
    """Redis stub that raises on every SET call."""

    def set(self, *_args, **_kwargs):
        raise ConnectionError("Redis connection lost")


def _build_init_data(user_id: int, auth_date: int, bot_token: str) -> str:
    """Build a valid Telegram initData string with correct HMAC."""
    payload = json.dumps(
        {
            "id": user_id,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
        }
    )
    data = {
        "auth_date": str(auth_date),
        "query_id": "AAE",
        "user": payload,
    }
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(data.items())
    )
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    hash_value = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    data["hash"] = hash_value
    return urlencode(data)


# ─── Integration tests (via TestClient) ──────────────────────────────


class TestInitDataReplayIntegration:
    """End-to-end tests for replay protection through the auth endpoint."""

    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        monkeypatch.setenv("PRODUCTION", "false")
        monkeypatch.setenv("REDIS_URL", "redis://fake:6379/0")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self):
        """Disable slowapi rate limiter so integration tests don't exhaust
        the 10/minute limit when running alongside other test modules."""
        from app.core.rate_limit import limiter

        prev = limiter.enabled
        limiter.enabled = False
        yield
        limiter.enabled = prev

    @pytest.fixture()
    def fake_redis(self):
        return FakeRedis()

    @pytest.fixture()
    def patched_client(self, client, fake_redis):
        """TestClient with replay Redis patched to use FakeRedis."""
        with patch(
            "app.api.v1.auth.get_redis_client", return_value=fake_redis
        ):
            yield client

    def test_first_request_succeeds(self, patched_client, fake_redis):
        init_data = _build_init_data(11111, int(time.time()), "test-token")
        resp = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "access_token" in body
        # The dedup key should now exist in the store
        assert len(fake_redis._store) == 1

    def test_second_request_rejected_as_replay(
        self, patched_client, fake_redis
    ):
        init_data = _build_init_data(22222, int(time.time()), "test-token")

        resp1 = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data}
        )
        assert resp1.status_code == 200

        resp2 = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data}
        )
        assert resp2.status_code == 401
        body = resp2.json()
        assert body["error"]["reason_code"] == "initdata_replay"
        assert body["error"]["message"] == "Authentication failed"

    def test_different_init_data_succeeds(self, patched_client, fake_redis):
        init_data_a = _build_init_data(33333, int(time.time()), "test-token")
        init_data_b = _build_init_data(44444, int(time.time()), "test-token")

        resp_a = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data_a}
        )
        assert resp_a.status_code == 200

        resp_b = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data_b}
        )
        assert resp_b.status_code == 200

    def test_after_ttl_expiry_succeeds_again(
        self, patched_client, fake_redis
    ):
        init_data = _build_init_data(55555, int(time.time()), "test-token")

        resp1 = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data}
        )
        assert resp1.status_code == 200

        # Simulate TTL expiry by clearing the Redis store
        fake_redis._store.clear()

        resp2 = patched_client.post(
            "/api/v1/auth/telegram", json={"init_data": init_data}
        )
        assert resp2.status_code == 200

    def test_redis_unavailable_dev_skips_check(self, client):
        """In dev mode with no Redis, replay check is skipped."""
        with patch("app.api.v1.auth.get_redis_client", return_value=None):
            init_data = _build_init_data(
                77777, int(time.time()), "test-token"
            )
            resp = client.post(
                "/api/v1/auth/telegram", json={"init_data": init_data}
            )
        assert resp.status_code == 200


# ─── Unit tests for _check_initdata_replay ───────────────────────────


class TestCheckInitdataReplayUnit:
    """Direct unit tests for the replay check function."""

    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
        monkeypatch.setenv("PRODUCTION", "false")
        monkeypatch.setenv("REDIS_URL", "redis://fake:6379/0")
        get_settings.cache_clear()
        yield
        get_settings.cache_clear()

    def test_ttl_zero_skips_check(self, monkeypatch):
        get_settings.cache_clear()
        monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "0")
        get_settings.cache_clear()

        from app.api.v1.auth import _check_initdata_replay

        result = _check_initdata_replay("anything")
        assert result is None

    def test_replay_detected_returns_401(self):
        from app.api.v1.auth import _check_initdata_replay

        fake = FakeRedis()
        # Pre-fill the store with the expected key
        settings = get_settings()
        digest = hashlib.sha256(b"test-init-data").hexdigest()
        key = f"tg:initdata:replay:{settings.environment}:{digest}"
        fake._store[key] = "1"

        with patch("app.api.v1.auth.get_redis_client", return_value=fake):
            result = _check_initdata_replay("test-init-data")

        assert result is not None
        assert result.status_code == 401
        body = json.loads(result.body)
        assert body["error"]["reason_code"] == "initdata_replay"

    def test_new_initdata_returns_none(self):
        from app.api.v1.auth import _check_initdata_replay

        fake = FakeRedis()
        with patch("app.api.v1.auth.get_redis_client", return_value=fake):
            result = _check_initdata_replay("fresh-init-data")

        assert result is None
        assert len(fake._store) == 1

    def test_redis_unavailable_production_returns_503(self, monkeypatch):
        """Fail-closed: production with no Redis → 503."""
        from app.api.v1.auth import _check_initdata_replay

        get_settings.cache_clear()
        monkeypatch.setenv("PRODUCTION", "false")
        get_settings.cache_clear()

        mock_settings = MagicMock()
        mock_settings.telegram_auth_ttl_seconds = 300
        mock_settings.production = True
        mock_settings.redis_url = "redis://fake:6379/0"
        mock_settings.environment = "test"

        with patch("app.api.v1.auth.get_redis_client", return_value=None), \
             patch("app.api.v1.auth.get_settings", return_value=mock_settings):
            result = _check_initdata_replay("some-data")

        assert result is not None
        assert result.status_code == 503

    def test_redis_error_production_returns_503(self, monkeypatch):
        """Fail-closed: production with Redis error → 503."""
        from app.api.v1.auth import _check_initdata_replay

        mock_settings = MagicMock()
        mock_settings.telegram_auth_ttl_seconds = 300
        mock_settings.production = True
        mock_settings.redis_url = "redis://fake:6379/0"
        mock_settings.environment = "test"

        with patch(
            "app.api.v1.auth.get_redis_client",
            return_value=ErrorRedis(),
        ), patch(
            "app.api.v1.auth.get_settings",
            return_value=mock_settings,
        ):
            result = _check_initdata_replay("some-data")

        assert result is not None
        assert result.status_code == 503

    def test_redis_error_dev_returns_none(self):
        """Dev mode with Redis error → skip (return None)."""
        from app.api.v1.auth import _check_initdata_replay

        with patch(
            "app.api.v1.auth.get_redis_client",
            return_value=ErrorRedis(),
        ):
            result = _check_initdata_replay("some-data")

        assert result is None

    def test_key_includes_environment_namespace(self):
        from app.api.v1.auth import _check_initdata_replay

        settings = get_settings()
        fake = FakeRedis()

        with patch("app.api.v1.auth.get_redis_client", return_value=fake):
            _check_initdata_replay("my-init-data")

        digest = hashlib.sha256(b"my-init-data").hexdigest()
        expected_key = f"tg:initdata:replay:{settings.environment}:{digest}"
        assert expected_key in fake._store
