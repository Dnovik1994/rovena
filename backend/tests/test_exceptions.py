from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User


def _create_user(client) -> User:
    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user = User(
            telegram_id=444444,
            username="errors",
            first_name="Err",
            last_name="Ors",
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


def test_global_exception_handler(client, monkeypatch):
    user = _create_user(client)
    token = create_access_token(str(user.id))
    captured = {"called": False}

    def fake_capture(exc):  # noqa: ANN001
        captured["called"] = True

    monkeypatch.setattr("sentry_sdk.capture_exception", fake_capture)

    def broken_db():  # noqa: ANN001
        raise RuntimeError("boom")

    from app.main import app

    app.dependency_overrides[get_db] = broken_db
    response = client.get("/api/v1/projects", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 500
    payload = response.json()
    assert payload["type"] == "internal_error"
    assert captured["called"] is True
