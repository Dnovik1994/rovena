import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from app.core.security import create_access_token
from app.core.settings import get_settings
from app.core.database import SessionLocal
from app.models.user import User


def _build_init_data(user_id: int, auth_date: int, bot_token: str) -> str:
    payload = json.dumps(
        {
            "id": user_id,
            "first_name": "Test",
            "last_name": "User",
            "username": "testuser",
        }
    )
    data = {
        "auth_date": str(auth_date),
        "query_id": "AAE",
        "user": payload,
    }
    data_check_string = "\n".join(f"{key}={value}" for key, value in sorted(data.items()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    hash_value = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    data["hash"] = hash_value
    return urlencode(data)


def test_inactive_user_blocked(client):
    with SessionLocal() as db:
        user = User(telegram_id=123456, username="inactive", is_active=False)
        db.add(user)
        db.commit()
        db.refresh(user)
        token = create_access_token(str(user.id))

    response = client.get(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "User inactive"


def test_init_data_replay_rejected(client):
    settings = get_settings()
    settings.telegram_auth_ttl_seconds = 1
    old_auth_date = int(time.time()) - 120
    init_data = _build_init_data(98765, old_auth_date, settings.telegram_bot_token)
    response = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert response.status_code == 401
    settings.telegram_auth_ttl_seconds = 0
