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
