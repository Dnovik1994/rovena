import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

import pytest
import jwt
from starlette.requests import Request

from app.api.deps import get_current_user_id
from app.core.database import SessionLocal
from app.core.security import create_access_token, decode_access_token
from app.core.settings import get_settings
from app.models.user import User
from app.services.telegram_auth import TelegramAuthError, validate_init_data


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
    secret_key = hmac.new(
        key=b"WebAppData",
        msg=bot_token.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    hash_value = hmac.new(
        key=secret_key,
        msg=data_check_string.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
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


def test_validate_init_data_accepts_valid_signature():
    settings = get_settings()
    previous_token = settings.telegram_bot_token
    previous_ttl = settings.telegram_auth_ttl_seconds

    try:
        settings.telegram_bot_token = "test-token"
        settings.telegram_auth_ttl_seconds = 300
        init_data = _build_init_data(12345, int(time.time()), settings.telegram_bot_token)

        parsed = validate_init_data(init_data)

        assert parsed["auth_date"]
        assert parsed["query_id"] == "AAE"
        assert "user" in parsed
    finally:
        settings.telegram_bot_token = previous_token
        settings.telegram_auth_ttl_seconds = previous_ttl


def test_validate_init_data_rejects_invalid_signature():
    settings = get_settings()
    previous_token = settings.telegram_bot_token
    previous_ttl = settings.telegram_auth_ttl_seconds

    try:
        settings.telegram_bot_token = "test-token"
        settings.telegram_auth_ttl_seconds = 300
        init_data = _build_init_data(12345, int(time.time()), settings.telegram_bot_token)
        tampered = init_data.replace("hash=", "hash=deadbeef", 1)

        with pytest.raises(TelegramAuthError, match="Invalid initData signature"):
            validate_init_data(tampered)
    finally:
        settings.telegram_bot_token = previous_token
        settings.telegram_auth_ttl_seconds = previous_ttl


def test_init_data_replay_rejected(client):
    settings = get_settings()
    previous_token = settings.telegram_bot_token
    previous_ttl = settings.telegram_auth_ttl_seconds

    try:
        settings.telegram_bot_token = "test-token"
        settings.telegram_auth_ttl_seconds = 1
        old_auth_date = int(time.time()) - 120
        init_data = _build_init_data(98765, old_auth_date, settings.telegram_bot_token)
        response = client.post("/api/v1/auth/telegram", json={"init_data": init_data})

        assert response.status_code == 401
        assert response.json()["error"]["reason_code"] == "auth_date_expired"
    finally:
        settings.telegram_auth_ttl_seconds = previous_ttl
        settings.telegram_bot_token = previous_token


def test_decode_access_token_accepts_trailing_newline():
    token = create_access_token("123")

    payload = decode_access_token(token + "\r\n")

    assert payload["sub"] == "123"
    assert payload["type"] == "access"


@pytest.mark.asyncio
async def test_legacy_numeric_sub_token_fallback_decodes_and_resolves_user_id():
    with SessionLocal() as db:
        user = User(telegram_id=22334455, username="legacy-sub-user", is_active=True)
        db.add(user)
        db.commit()
        db.refresh(user)

    settings = get_settings()
    legacy_token = jwt.encode(
        {"sub": user.id, "type": "access"},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )

    payload = decode_access_token(legacy_token)
    assert payload["sub"] == user.id

    request = Request({"type": "http", "method": "GET", "headers": []})
    resolved_user_id = await get_current_user_id(
        request=request,
        authorization=f"Bearer {legacy_token}",
    )

    assert isinstance(resolved_user_id, int)
    assert resolved_user_id == user.id
