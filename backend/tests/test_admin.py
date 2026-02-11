import hashlib
import hmac
import json
import time
from urllib.parse import urlencode

from fastapi import status

from app.core.security import create_access_token
from app.models.user import ADMIN_ROLES, User, UserRole
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


def test_403_does_not_invalidate_session(client):
    """After receiving 403 on an admin endpoint the same token must still
    work for regular user endpoints.  The frontend relies on this: it must
    NOT clear tokens on 403 (only on 401)."""
    user = _create_user(telegram_id=44001, is_admin=False)
    token = create_access_token(str(user.id))
    headers = {"Authorization": f"Bearer {token}"}

    # 1. 403 on admin endpoint
    resp_admin = client.get("/api/v1/admin/stats", headers=headers)
    assert resp_admin.status_code == status.HTTP_403_FORBIDDEN

    # 2. Regular /me still works with the same token
    resp_me = client.get("/api/v1/me", headers=headers)
    assert resp_me.status_code == status.HTTP_200_OK
    assert resp_me.json()["id"] == user.id


def test_401_on_invalid_token(client):
    """An invalid/expired token must return 401, signalling the frontend
    to attempt a token refresh (and clear tokens if refresh fails)."""
    headers = {"Authorization": "Bearer invalid-token-value"}

    resp = client.get("/api/v1/me", headers=headers)
    assert resp.status_code == status.HTTP_401_UNAUTHORIZED


# ─── Unified admin authorization (role as source of truth) ──────────


def test_role_admin_grants_admin_access(client):
    """User with role=admin can access admin endpoints (role is source of truth)."""
    with SessionLocal() as db:
        user = User(
            telegram_id=10001,
            username="role_admin",
            role=UserRole.admin,
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id

    token = create_access_token(str(uid))
    resp = client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_200_OK


def test_role_superadmin_grants_admin_access(client):
    """User with role=superadmin can access admin endpoints."""
    with SessionLocal() as db:
        user = User(
            telegram_id=10002,
            username="role_superadmin",
            role=UserRole.superadmin,
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id

    token = create_access_token(str(uid))
    resp = client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_200_OK


def test_role_user_with_is_admin_flag_denied(client):
    """is_admin=True but role=user must NOT grant admin access (role is source of truth)."""
    with SessionLocal() as db:
        user = User(
            telegram_id=10003,
            username="stale_flag",
            role=UserRole.user,
            is_admin=True,  # stale flag — should be ignored
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id

    token = create_access_token(str(uid))
    resp = client.get("/api/v1/admin/stats", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_login_does_not_downgrade_existing_admin(client, monkeypatch):
    """Login with ADMIN_TELEGRAM_ID unset must NOT downgrade existing admin."""
    from app.core.settings import get_settings

    admin_tid = 10004
    # Create an admin user first.
    _create_user(telegram_id=admin_tid, is_admin=True)

    # Login with ADMIN_TELEGRAM_ID pointing to a different user.
    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", "99999")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    init_data = _make_init_data(admin_tid)
    resp = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert resp.status_code == status.HTTP_200_OK

    with SessionLocal() as db:
        user = db.query(User).filter(User.telegram_id == admin_tid).first()
        assert user is not None
        # Must still be admin — not downgraded.
        assert user.role == UserRole.admin
        assert user.is_admin is True

    get_settings.cache_clear()


def test_bootstrap_does_not_downgrade_superadmin(monkeypatch):
    """Bootstrap must not downgrade a superadmin to admin."""
    from app import main

    with SessionLocal() as db:
        user = User(
            telegram_id=10005,
            username="superadmin_user",
            role=UserRole.superadmin,
            is_admin=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id

    monkeypatch.setattr(main.settings, "admin_user_id", uid)
    monkeypatch.setattr(main.settings, "admin_telegram_id", None)

    main._bootstrap_admin()

    with SessionLocal() as db:
        refreshed = db.get(User, uid)
        assert refreshed is not None
        # Must remain superadmin, not downgraded to admin.
        assert refreshed.role == UserRole.superadmin
        assert refreshed.is_admin is True


def test_me_returns_is_admin_consistent_with_role(client):
    """/me must return is_admin derived from role, not from the DB column."""
    # Create user with role=admin but is_admin=False (inconsistent DB state).
    with SessionLocal() as db:
        user = User(
            telegram_id=10006,
            username="inconsistent",
            role=UserRole.admin,
            is_admin=False,  # DB out of sync
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        uid = user.id

    token = create_access_token(str(uid))
    resp = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    # is_admin must be derived from role, so True even though DB says False.
    assert data["is_admin"] is True
    assert data["role"] == "admin"


def test_token_response_includes_role_and_is_admin(client, monkeypatch):
    """TokenResponse from login must include is_admin and role fields."""
    from app.core.settings import get_settings

    admin_tid = 10007
    get_settings.cache_clear()
    monkeypatch.setenv("ADMIN_TELEGRAM_ID", str(admin_tid))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-bot-token")
    monkeypatch.setenv("TELEGRAM_AUTH_TTL_SECONDS", "300")
    get_settings.cache_clear()

    init_data = _make_init_data(admin_tid)
    resp = client.post("/api/v1/auth/telegram", json={"init_data": init_data})
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert data["is_admin"] is True
    assert data["role"] == "admin"

    get_settings.cache_clear()


def test_admin_user_update_syncs_is_admin(client):
    """Changing role via admin PATCH must keep is_admin in sync."""
    admin = _create_user(telegram_id=10008, is_admin=True)
    target = _create_user(telegram_id=10009, is_admin=False)
    token = create_access_token(str(admin.id))
    headers = {"Authorization": f"Bearer {token}"}

    # Promote to admin
    resp = client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"role": "admin"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["role"] == "admin"
    assert resp.json()["is_admin"] is True

    # Demote back to user
    resp = client.patch(
        f"/api/v1/admin/users/{target.id}",
        json={"role": "user"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["role"] == "user"
    assert resp.json()["is_admin"] is False
