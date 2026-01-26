import json

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.user import User
from app.services.websocket_manager import manager


def test_ws_broadcast(client):
    with SessionLocal() as db:
        user = User(telegram_id=3001, username="ws-user", first_name="Web")
        db.add(user)
        db.commit()
        db.refresh(user)

    token = create_access_token(str(user.id))

    with client.websocket_connect(f"/ws/status?token={token}") as websocket:
        manager.broadcast_sync({"type": "account_update", "account_id": 1, "status": "warming"})
        payload = json.loads(websocket.receive_text())
        assert payload["type"] == "account_update"
