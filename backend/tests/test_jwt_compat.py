from app.core.security import create_access_token, decode_access_token
from app.models.user import User


def test_create_access_token_with_int_subject_decodes_with_string_sub():
    token = create_access_token(1)
    payload = decode_access_token(token)
    assert payload["sub"] == "1"
    assert payload["type"] == "access"


def test_me_accepts_token_created_with_int_subject(client, db_session):
    user = User(telegram_id=123456, username="jwt_int_sub_user")
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)

    token = create_access_token(user.id)
    response = client.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == user.id
