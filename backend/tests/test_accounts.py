from fastapi import status
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.user import User


def _create_user(db: Session, telegram_id: int, is_admin: bool = False) -> User:
    user = User(telegram_id=telegram_id, username=f"user{telegram_id}", is_admin=is_admin)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_accounts_isolated_by_owner(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user_one = _create_user(db, telegram_id=5001)
        user_two = _create_user(db, telegram_id=6002)

        account_one = TelegramAccount(
            owner_user_id=user_one.id,
            tg_user_id=111111111,
            phone_e164="+10000000001",
            status=TelegramAccountStatus.new,
        )
        account_two = TelegramAccount(
            owner_user_id=user_two.id,
            tg_user_id=222222222,
            phone_e164="+10000000002",
            status=TelegramAccountStatus.new,
        )
        db.add_all([account_one, account_two])
        db.commit()

        token_one = create_access_token(str(user_one.id))
        token_two = create_access_token(str(user_two.id))
    finally:
        db.close()

    response_one = client.get(
        "/api/v1/tg-accounts", headers={"Authorization": f"Bearer {token_one}"}
    )
    response_two = client.get(
        "/api/v1/tg-accounts", headers={"Authorization": f"Bearer {token_two}"}
    )

    assert response_one.status_code == status.HTTP_200_OK
    assert response_two.status_code == status.HTTP_200_OK
    assert len(response_one.json()) == 1
    assert len(response_two.json()) == 1
    assert response_one.json()[0]["tg_user_id"] == 111111111
    assert response_two.json()[0]["tg_user_id"] == 222222222
