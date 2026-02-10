from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User


def _create_user(client) -> User:
    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user = User(
            telegram_id=555555,
            username="onboard",
            first_name="On",
            last_name="Board",
            is_admin=False,
            is_active=True,
            role="user",
            tariff_id=1,
            onboarding_completed=False,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user
    finally:
        db_gen.close()


def test_onboarding_flow(client):
    user = _create_user(client)
    token = create_access_token(str(user.id))

    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["onboarding_completed"] is False

    response = client.patch(
        "/api/v1/users/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"onboarding_completed": True},
    )
    assert response.status_code == 200
    assert response.json()["onboarding_completed"] is True


def test_onboarding_repeated_calls_are_stable(client):
    user = _create_user(client)
    token = create_access_token(str(user.id))

    for value in [True, False, True, True, False]:
        response = client.patch(
            "/api/v1/users/me/onboarding",
            headers={"Authorization": f"Bearer {token}"},
            json={"onboarding_completed": value},
        )
        assert response.status_code == 200
        assert response.json()["onboarding_completed"] is value


def test_onboarding_invalidates_user_cache(client, monkeypatch):
    user = _create_user(client)
    token = create_access_token(str(user.id))

    deleted_keys = []

    async def fake_delete(key: str) -> None:
        deleted_keys.append(key)

    from app.api.v1 import users as users_api

    monkeypatch.setattr(users_api, "delete", fake_delete)

    response = client.patch(
        "/api/v1/users/me/onboarding",
        headers={"Authorization": f"Bearer {token}"},
        json={"onboarding_completed": True},
    )

    assert response.status_code == 200
    assert deleted_keys == [f"user:{user.id}"]


def test_read_me_handles_null_onboarding_completed(client):
    user = _create_user(client)
    user.onboarding_completed = None

    client.app.dependency_overrides[get_current_active_user] = lambda: user
    try:
        response = client.get("/api/v1/me")
    finally:
        client.app.dependency_overrides.pop(get_current_active_user, None)

    assert response.status_code == 200
    assert response.json()["onboarding_completed"] is False
