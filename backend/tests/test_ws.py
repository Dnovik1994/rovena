import json

import pytest

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.user import User
from app.services.websocket_manager import manager


def test_ws_broadcast(client, monkeypatch):
    with SessionLocal() as db:
        user = User(telegram_id=3001, username="ws-user", first_name="Web")
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(str(user.id))

    # Capture messages that broadcast_sync would publish to Redis
    published: list[dict] = []
    monkeypatch.setattr(
        manager,
        "_publish_to_redis",
        lambda payload: published.append(payload),
    )

    with client.websocket_connect(f"/ws/status?token={token}") as websocket:
        manager.broadcast_sync(
            {"type": "account_update", "account_id": 1, "status": "warming"},
        )
        # broadcast_sync falls back to _publish_to_redis in test context
        # (no running async loop). Verify the payload was published.
        assert len(published) == 1
        assert published[0]["type"] == "account_update"
        assert published[0]["status"] == "warming"
