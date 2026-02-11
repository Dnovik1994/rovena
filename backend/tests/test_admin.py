import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import status

from app.core.security import create_access_token
from app.models.user import User, UserRole
from app.core.database import SessionLocal


def _create_user(telegram_id: int, is_admin: bool) -> User:
    with SessionLocal() as db:
        user = User(
            telegram_id=telegram_id,
            username=f"user{telegram_id}",
            is_admin=is_admin,
            role=UserRole.admin if is_admin else UserRole.user,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _make_init_data(telegram_id: int, bot_token: str = "test-bot-token") -> str:
    """Build valid Telegram initData with correct HMAC for the given user."""
    auth_date = str(int(time.time()))
    user_json = json.dumps({"id": telegram_id, "first_name": "Test", "username": "testuser"})
    data_pairs = [("auth_date", auth_date), ("user", user_json)]
    sorted_pairs = sorted(data_pairs, key=lambda p: p[0])
    data_check_string = "\n".join(f"{k}={v}" for k, v in sorted_pairs)
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    hash_value = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    return urlencode(data_pairs + [("hash", hash_value)])


def test_admin_stats_requires_admin(client):
    user = _create_user(telegram_id=1111, is_admin=False)
    token = create_access_token(str(user.id))

    response = client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_users_ok_for_admin(client):
    admin = _create_user(telegram_id=2222, is_admin=True)
    token = create_access_token(str(admin.id))

    response = client.get("/api/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert "items" in payload


def test_admin_me_requires_admin(client):
    user = _create_user(telegram_id=3333, is_admin=False)
    token = create_access_token(str(user.id))

    response = client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_admin_me_for_admin(client):
    admin = _create_user(telegram_id=4444, is_admin=True)
    token = create_access_token(str(admin.id))

    response = client.get("/api/v1/admin/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["id"] == admin.id


def test_admin_bootstrap_sets_flag(monkeypatch):
    from app import main

    user = _create_user(telegram_id=5555, is_admin=False)
    monkeypatch.setattr(main.settings, "admin_user_id", user.id)
    monkeypatch.setattr(main.settings, "admin_telegram_id", None)

    main._bootstrap_admin()

    with SessionLocal() as db:
        refreshed = db.get(User, user.id)
        assert refreshed is not None
        assert refreshed.is_admin is True
        assert refreshed.role == UserRole.admin


# ─── Admin flag via Telegram login ───────────────────────────────────


def test_telegram_login_new_user_gets_admin_when_configured(client, monkeypatch):
    """New user whose telegram_id matches ADMIN_TELEGRAM_ID gets is_admin=True."""
    from app.core.settings import get_settings

    admin_tid = 99001
    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", str(admin_tid))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    init_data = _make_init_data(admin_tid)
    response = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert response.status_code == status.HTTP_200_OK
    assert "access_token" in response.json()

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == admin_tid).first()
        assert user is not None
        assert user.is_admin is True
        assert user.role == UserRole.admin

    get_settings.cache_clear()


def test_telegram_login_new_user_not_admin_when_different_id(client, monkeypatch):
    """New user whose telegram_id does NOT match ADMIN_TELEGRAM_ID gets is_admin=False."""
    from app.core.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "99002")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    regular_tid = 88001
    init_data = _make_init_data(regular_tid)
    response = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert response.status_code == status.HTTP_200_OK

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == regular_tid).first()
        assert user is not None
        assert user.is_admin is False
        assert user.role == UserRole.user

    get_settings.cache_clear()


def test_telegram_login_existing_user_promoted_to_admin(client, monkeypatch):
    """Existing non-admin user gets promoted when ADMIN_TELEGRAM_ID is set to their id."""
    from app.core.settings import get_settings

    existing_tid = 77001
    existing = _create_user(telegram_id=existing_tid, is_admin=False)
    assert existing.is_admin is False

    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", str(existing_tid))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    init_data = _make_init_data(existing_tid)
    response = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert response.status_code == status.HTTP_200_OK

    with SessionLocal() as db:
        user = db.get(User, existing.id)
        assert user is not None
        assert user.is_admin is True
        assert user.role == UserRole.admin

    get_settings.cache_clear()


def test_admin_user_can_access_admin_endpoint_after_login(client, monkeypatch):
    """Full flow: login as admin → /me shows is_admin → admin endpoint returns 200."""
    from app.core.settings import get_settings

    admin_tid = 66001
    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", str(admin_tid))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    init_data = _make_init_data(admin_tid)
    login_resp = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert login_resp.status_code == status.HTTP_200_OK
    access_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # /me should show is_admin=true
    me_resp = client.get("/api/v1/me", headers=headers)
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.json()["is_admin"] is True

    # admin endpoint should return 200
    stats_resp = client.get("/api/v1/admin/stats", headers=headers)
    assert stats_resp.status_code == status.HTTP_200_OK

    get_settings.cache_clear()


def test_non_admin_user_denied_admin_endpoint_after_login(client, monkeypatch):
    """Full flow: login as regular user → admin endpoint returns 403."""
    from app.core.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "55999")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    regular_tid = 55001
    init_data = _make_init_data(regular_tid)
    login_resp = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert login_resp.status_code == status.HTTP_200_OK
    access_token = login_resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {access_token}"}

    # /me should show is_admin=false
    me_resp = client.get("/api/v1/me", headers=headers)
    assert me_resp.status_code == status.HTTP_200_OK
    assert me_resp.json()["is_admin"] is False

    # admin endpoint should return 403
    stats_resp = client.get("/api/v1/admin/stats", headers=headers)
    assert stats_resp.status_code == status.HTTP_403_FORBIDDEN

    get_settings.cache_clear()
