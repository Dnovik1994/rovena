from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.tariff import Tariff
from app.models.user import User, UserRole


def _create_admin() -> User:
    with SessionLocal() as db:
        admin = User(
            telegram_id=7001,
            username="admin",
            is_admin=True,
            role=UserRole.admin,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin


def _create_user() -> User:
    with SessionLocal() as db:
        user = User(telegram_id=7002, username="user", is_admin=False)
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def test_tariff_crud_and_assignment(client):
    admin = _create_admin()
    user = _create_user()
    token = create_access_token(str(admin.id))

    response = client.get("/api/v1/admin/tariffs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == status.HTTP_200_OK
    assert len(response.json()) >= 2

    response = client.post(
        "/api/v1/admin/tariffs",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "name": "Starter",
            "max_accounts": 3,
            "max_invites_day": 30,
            "price": 9.99,
        },
    )
    assert response.status_code == status.HTTP_201_CREATED
    created = response.json()

    response = client.patch(
        f"/api/v1/admin/tariffs/{created['id']}",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Starter Plus", "max_invites_day": 40},
    )
    assert response.status_code == status.HTTP_200_OK
    updated = response.json()
    assert updated["name"] == "Starter Plus"

    response = client.patch(
        f"/api/v1/admin/users/{user.id}/tariff",
        headers={"Authorization": f"Bearer {token}"},
        json={"tariff_id": updated["id"]},
    )
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["tariff"]["id"] == updated["id"]

    response = client.delete(
        f"/api/v1/admin/tariffs/{updated['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST

    with SessionLocal() as db:
        db.query(User).filter(User.id == user.id).update({"tariff_id": 1})
        db.commit()

    response = client.delete(
        f"/api/v1/admin/tariffs/{updated['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_204_NO_CONTENT

    with SessionLocal() as db:
        assert db.get(Tariff, updated["id"]) is None
