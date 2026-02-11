from fastapi import status
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.user import User, UserRole


def _create_user(db: Session, telegram_id: int, is_admin: bool = False) -> User:
    role = UserRole.admin if is_admin else UserRole.user
    user = User(telegram_id=telegram_id, username=f"user{telegram_id}", is_admin=is_admin, role=role)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_proxies_admin_only(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user = _create_user(db, telegram_id=7001, is_admin=False)
        admin = _create_user(db, telegram_id=8001, is_admin=True)

        token_user = create_access_token(str(user.id))
        token_admin = create_access_token(str(admin.id))
    finally:
        db.close()

    response_user = client.get(
        "/api/v1/proxies", headers={"Authorization": f"Bearer {token_user}"}
    )
    response_admin = client.get(
        "/api/v1/proxies", headers={"Authorization": f"Bearer {token_admin}"}
    )

    assert response_user.status_code == status.HTTP_403_FORBIDDEN
    assert response_admin.status_code == status.HTTP_200_OK
