import importlib
from typing import Optional

import pytest

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    pytest.skip("httpx is required for TestClient-based tests", allow_module_level=True)

from fastapi.testclient import TestClient


def _build_client(monkeypatch, production: bool, origins: str):
    monkeypatch.setenv("PRODUCTION", "true" if production else "false")
    monkeypatch.setenv("CORS_ORIGINS", origins)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    from app.core.settings import get_settings

    get_settings.cache_clear()
    import app.main as main

    importlib.reload(main)
    return TestClient(main.app)


def _build_settings(monkeypatch, origins: Optional[str]):
    if origins is None:
        monkeypatch.delenv("CORS_ORIGINS", raising=False)
    else:
        monkeypatch.setenv("CORS_ORIGINS", origins)
    monkeypatch.setenv("JWT_SECRET", "test-secret")
    from app.core.settings import Settings

    return Settings()


def test_cors_dev_allows_any_origin(monkeypatch):
    client = _build_client(monkeypatch, production=False, origins="https://example.com")
    response = client.options(
        "/health",
        headers={
            "Origin": "https://example.com",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "*"


def test_cors_prod_restricts_origin(monkeypatch):
    client = _build_client(
        monkeypatch,
        production=True,
        origins='["https://kass.freecrm.biz","https://web.telegram.org"]',
    )
    response = client.options(
        "/health",
        headers={
            "Origin": "https://kass.freecrm.biz",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "https://kass.freecrm.biz"


def test_cors_origins_accepts_json_list(monkeypatch):
    settings = _build_settings(
        monkeypatch,
        origins='["http://localhost:5173","http://127.0.0.1:5173"]',
    )
    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_cors_origins_accepts_csv(monkeypatch):
    settings = _build_settings(
        monkeypatch,
        origins="http://localhost:5173,http://127.0.0.1:5173",
    )
    assert settings.cors_origins == [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]


def test_cors_origins_accepts_single(monkeypatch):
    settings = _build_settings(monkeypatch, origins="http://localhost:5173")
    assert settings.cors_origins == ["http://localhost:5173"]


def test_cors_origins_accepts_empty_string(monkeypatch):
    settings = _build_settings(monkeypatch, origins="")
    assert settings.cors_origins == []


def test_cors_origins_missing_env(monkeypatch):
    settings = _build_settings(monkeypatch, origins=None)
    assert settings.cors_origins == []
