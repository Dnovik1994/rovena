from __future__ import annotations

import importlib
import logging
import warnings

import pytest

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    pytest.skip("httpx is required for async tests", allow_module_level=True)

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from httpx import ASGITransport

from app.main import app


def _alembic_config() -> Config:
    from pathlib import Path

    backend_root = Path(__file__).resolve().parents[1]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "alembic"))
    return config


@pytest.mark.asyncio
async def test_health_after_migration(mock_alembic, mock_redis):
    command.upgrade(_alembic_config(), "head")
    assert mock_alembic
    assert mock_alembic[0][1] == "head"

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_startup_logs(mock_redis, caplog):
    caplog.set_level(logging.INFO)
    with TestClient(app):
        pass

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "Redis connected" in messages
    assert "Application startup complete" in messages
    assert "OperationalError" not in messages


@pytest.mark.asyncio
async def test_smoke_api(monkeypatch, mock_redis):
    monkeypatch.setenv("COMMIT_SHA", "test-sha")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        health_response = await client.get("/health")
        version_response = await client.get("/version")

    assert health_response.status_code == 200
    assert version_response.status_code == 200
    assert version_response.json()["commit"] != "unknown"


def test_worker_startup(caplog):
    caplog.set_level(logging.INFO)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        from app import workers

        importlib.reload(workers)

    warning_messages = [str(item.message) for item in caught]
    assert not any("SecurityWarning" in message for message in warning_messages)
    assert not any("deprecated" in message.lower() for message in warning_messages)

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "Task queue ready" in messages
    assert workers.celery_app.conf.broker_connection_retry_on_startup is True
