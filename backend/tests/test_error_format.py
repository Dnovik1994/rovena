from fastapi.testclient import TestClient

from app.main import app


def test_unhandled_exception_format():
    @app.get("/__test/error")
    def trigger_error():
        raise RuntimeError("boom")

    client = TestClient(app)
    response = client.get("/__test/error")
    assert response.status_code == 500
    assert response.json() == {"error": {"code": "500", "message": "Internal error"}}
