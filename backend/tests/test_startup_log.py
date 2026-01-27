import logging

from fastapi.testclient import TestClient

from app.main import APP_VERSION, app


def test_startup_logs_version_commit_env(caplog):
    caplog.set_level(logging.INFO, logger="app.main")
    with TestClient(app):
        pass

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert f"version={APP_VERSION}" in messages
    assert "commit=" in messages
    assert "env=PRODUCTION=" in messages
