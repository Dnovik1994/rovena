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
    payload = response.json()
    assert payload["status"] in {"ok", "warn", "fail"}
    assert "checks" in payload
    assert "timestamp" in payload
    assert "version" in payload


def test_health_fail_returns_503(db_session, monkeypatch):
    from fastapi.testclient import TestClient
    from app.main import app as main_app
    from app.core.database import get_db

    def raise_db_error(*_args, **_kwargs):
        raise RuntimeError("DB unavailable")

    monkeypatch.setattr(db_session, "execute", raise_db_error)

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    main_app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(main_app) as test_client:
            response = test_client.get("/health")
    finally:
        main_app.dependency_overrides.clear()

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    payload = response.json()
    assert payload["status"] == "fail"
    assert "checks" in payload


def test_auth_invalid_initdata(client):
    response = client.post("/api/v1/auth/telegram", json={"init_data": "bad"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    body = response.json()
    assert body["error"]["message"] == "Authentication failed"
    assert body["error"]["reason_code"] in {
        "missing_init_data",
        "parse_failed",
        "missing_hash",
        "hmac_mismatch",
        "auth_date_expired",
    }


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
