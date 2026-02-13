"""Tests that tokens created by create_access_token are accepted by the
validation pipeline (decode_access_token, get_current_user_id, /api/v1/me).

These tests would FAIL before the fix because:
- create_access_token(1) produced sub=1 (int) instead of sub="1" (str)
- tokens with trailing whitespace caused JWTError in jwt.decode()
- `if not user_id` rejected sub="0" as falsy
"""

from jose import JWTError, jwt
import pytest

from app.core.database import SessionLocal
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
)
from app.core.settings import get_settings
from app.models.user import User


# ── Unit: round-trip create -> decode ──────────────────────────────────


def test_create_access_token_with_int_subject():
    """create_access_token(1) must produce the same token as create_access_token('1')."""
    token_int = create_access_token(1)
    token_str = create_access_token("1")

    payload_int = decode_access_token(token_int)
    payload_str = decode_access_token(token_str)

    assert payload_int["sub"] == "1"
    assert payload_str["sub"] == "1"
    assert payload_int["type"] == "access"


def test_create_refresh_token_with_int_subject():
    """create_refresh_token(1) must coerce subject to string."""
    token = create_refresh_token(1)
    payload = decode_refresh_token(token)
    assert payload["sub"] == "1"
    assert payload["type"] == "refresh"


def test_decode_access_token_strips_whitespace():
    """Tokens with trailing whitespace/newlines must still decode."""
    token = create_access_token("42")
    # Simulate shell artifacts: trailing newline, carriage return, spaces
    assert decode_access_token(token + "\n")["sub"] == "42"
    assert decode_access_token(token + "\r\n")["sub"] == "42"
    assert decode_access_token("  " + token + "  ")["sub"] == "42"


def test_decode_rejects_wrong_token_type():
    """Refresh token must not pass as access token and vice versa."""
    access = create_access_token("1")
    refresh = create_refresh_token("1")

    with pytest.raises(JWTError, match="Invalid token type"):
        decode_refresh_token(access)

    with pytest.raises(JWTError, match="Invalid token type"):
        decode_access_token(refresh)


def test_sub_claim_is_always_string():
    """The 'sub' claim in the JWT payload must always be a string."""
    settings = get_settings()
    for subject in [1, "1", 42, "42"]:
        token = create_access_token(subject)
        raw = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
        assert isinstance(raw["sub"], str), f"sub must be str, got {type(raw['sub'])} for input {subject!r}"


# ── Integration: token accepted by /api/v1/me ─────────────────────────


def test_me_accepts_token_from_create_access_token_int(client):
    """Token from create_access_token(user.id)  (int) must be accepted by /me."""
    with SessionLocal() as db:
        user = User(
            telegram_id=770001,
            username="token_int_test",
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    # Pass integer — the pre-fix code would produce sub=<int> and possibly fail
    token = create_access_token(user_id)
    resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == user_id


def test_me_accepts_token_from_create_access_token_str(client):
    """Token from create_access_token(str(user.id)) must be accepted by /me."""
    with SessionLocal() as db:
        user = User(
            telegram_id=770002,
            username="token_str_test",
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    token = create_access_token(str(user_id))
    resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["id"] == user_id


def test_me_accepts_token_with_trailing_whitespace(client):
    """Token with trailing newline (shell artifact) must be accepted by /me."""
    with SessionLocal() as db:
        user = User(
            telegram_id=770003,
            username="token_ws_test",
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    token = create_access_token(user_id)
    # Simulate trailing \r\n from docker exec output
    resp = client.get(
        "/api/v1/me",
        headers={"Authorization": f"Bearer {token}\r\n"},
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == user_id


# ── Backward compatibility: old tokens with int sub still decode ───────


def test_legacy_int_sub_token_still_accepted(client):
    """Tokens issued before the fix (sub as int) must still be accepted."""
    settings = get_settings()
    with SessionLocal() as db:
        user = User(
            telegram_id=770004,
            username="legacy_test",
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        user_id = user.id

    # Manually craft a token with integer sub (pre-fix format)
    from datetime import datetime, timedelta, timezone

    legacy_payload = {
        "sub": user_id,  # integer, not string — legacy format
        "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        "type": "access",
    }
    legacy_token = jwt.encode(
        legacy_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )

    resp = client.get(
        "/api/v1/me", headers={"Authorization": f"Bearer {legacy_token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["id"] == user_id
