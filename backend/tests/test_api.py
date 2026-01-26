from fastapi import status
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.project import Project
from app.models.user import User


def _create_user(db: Session, telegram_id: int) -> User:
    user = User(telegram_id=telegram_id, username=f"user{telegram_id}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_health_ok(client):
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    assert response.json() == {"status": "ok"}


def test_auth_invalid_initdata(client):
    response = client.post("/api/v1/auth/telegram", json={"init_data": "bad"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    body = response.json()
    assert "error" in body


def test_projects_isolated_by_owner(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user_one = _create_user(db, telegram_id=1001)
        user_two = _create_user(db, telegram_id=2002)

        project_one = Project(owner_id=user_one.id, name="One", description=None)
        project_two = Project(owner_id=user_two.id, name="Two", description=None)
        db.add_all([project_one, project_two])
        db.commit()

        token_one = create_access_token(str(user_one.id))
        token_two = create_access_token(str(user_two.id))
    finally:
        db.close()

    response_one = client.get(
        "/api/v1/projects", headers={"Authorization": f"Bearer {token_one}"}
    )
    response_two = client.get(
        "/api/v1/projects", headers={"Authorization": f"Bearer {token_two}"}
    )

    assert response_one.status_code == status.HTTP_200_OK
    assert response_two.status_code == status.HTTP_200_OK

    projects_one = response_one.json()
    projects_two = response_two.json()

    assert len(projects_one) == 1
    assert len(projects_two) == 1
    assert projects_one[0]["name"] == "One"
    assert projects_two[0]["name"] == "Two"
