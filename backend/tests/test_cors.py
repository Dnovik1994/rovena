import importlib

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
        origins="https://kass.freecrm.biz,https://web.telegram.org",
    )
    response = client.options(
        "/health",
        headers={
            "Origin": "https://kass.freecrm.biz",
            "Access-Control-Request-Method": "GET",
        },
    )
    assert response.headers.get("access-control-allow-origin") == "https://kass.freecrm.biz"
