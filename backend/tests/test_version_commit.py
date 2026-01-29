from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app


def test_version_commit_is_not_unknown(monkeypatch):
    monkeypatch.setenv("COMMIT_SHA", "abcdef1")

    with TestClient(app) as client:
        response = client.get("/version")

    assert response.status_code == 200
    payload = response.json()
    assert payload["commit"] != "unknown"
    assert payload["commit"] == "abcdef1"
