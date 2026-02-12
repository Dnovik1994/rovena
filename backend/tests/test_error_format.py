import pytest

try:
    import httpx  # noqa: F401
except ModuleNotFoundError:
    pytest.skip("httpx is required for TestClient-based tests", allow_module_level=True)

from fastapi.testclient import TestClient

from app.main import app


def test_unhandled_exception_format():
    @app.get("/__test/error")
    def trigger_error():
        raise RuntimeError("boom")

    client = TestClient(app)
    response = client.get("/__test/error")
    assert response.status_code == 500
    body = response.json()
    assert body == {"error": {"code": "INTERNAL_ERROR", "message": "Internal error", "status": 500}}


def test_unhandled_exception_on_api_route():
    """Errors under /api/ must use the same envelope (never {"type":"internal_error"})."""

    @app.get("/api/__test/error")
    def trigger_api_error():
        raise RuntimeError("api boom")

    client = TestClient(app)
    response = client.get("/api/__test/error")
    assert response.status_code == 500
    body = response.json()
    assert "type" not in body, "must not return {\"type\": \"internal_error\"}"
    assert body == {"error": {"code": "INTERNAL_ERROR", "message": "Internal error", "status": 500}}


def test_not_found_format():
    client = TestClient(app)
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404
    body = response.json()
    assert body == {"error": {"code": "NOT_FOUND", "message": "Not Found", "status": 404}}


def test_bare_api_returns_not_found():
    """GET /api/ should return 404 in the standard envelope, not 500."""
    client = TestClient(app)
    response = client.get("/api/")
    assert response.status_code == 404
    body = response.json()
    assert "type" not in body
    assert body["error"]["status"] == 404
    assert body["error"]["code"] == "NOT_FOUND"
