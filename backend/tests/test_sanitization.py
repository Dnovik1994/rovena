from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User


def _create_user(client) -> User:
    override = client.app.dependency_overrides[get_db]
    db_gen = override()
    db = next(db_gen)
    try:
        user = User(
            telegram_id=888888,
            username="sanitize",
            first_name="San",
            last_name="Test",
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


def test_html_sanitization(client):
    user = _create_user(client)
    token = create_access_token(str(user.id))
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "<script>alert(1)</script>", "description": "ok"},
    )
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "&lt;script&gt;alert(1)&lt;/script&gt;"


def test_sql_injection_rejected(client):
    user = _create_user(client)
    token = create_access_token(str(user.id))
    response = client.post(
        "/api/v1/projects",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": "Project'; DROP TABLE users; --", "description": "bad"},
    )
    assert response.status_code == 422
