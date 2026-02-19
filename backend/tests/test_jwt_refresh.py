from datetime import datetime, timedelta, timezone

import jwt

from app.core.database import get_db
from app.core.security import create_refresh_token, hash_token
from app.core.settings import get_settings
from app.models.user import User


def _create_user(client) -> User:
    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user = User(
            telegram_id=999999,
            username="tester",
            first_name="Test",
            last_name="User",
            is_admin=False,
            is_active=True,
            role="user",
            tariff_id=1,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db_gen.close()


def test_access_token_expired(client):
    user = _create_user(client)
    settings = get_settings()
    expired_payload = {
        "sub": str(user.id),
        "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        "type": "access",
    }
    expired_token = jwt.encode(
        expired_payload, settings.jwt_secret, algorithm=settings.jwt_algorithm
    )

    response = client.get(
        "/api/v1/projects", headers={"Authorization": f"Bearer {expired_token}"}
    )
    assert response.status_code == 401


def test_refresh_token_flow(client):
    user = _create_user(client)
    refresh_token = create_refresh_token(str(user.id))

    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user.refresh_token = hash_token(refresh_token)
        db.commit()
    finally:
        db_gen.close()

    response = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
    assert response.status_code == 200
    payload = response.json()
    assert payload["access_token"]
    assert payload["refresh_token"]

    db_gen = override()
    db = next(db_gen)
    try:
        updated = db.get(User, user.id)
        assert updated.refresh_token == hash_token(payload["refresh_token"])
    finally:
        db_gen.close()


def test_refresh_token_invalid(client):
    response = client.post(
        "/api/v1/auth/refresh", json={"refresh_token": "invalid.invalid.invalid"}
    )
    assert response.status_code == 401
