from __future__ import annotations

from app.workers import celery_app


def test_broker_connection_retry_on_startup_enabled():
    assert celery_app.conf.broker_connection_retry_on_startup is True
