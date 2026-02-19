from unittest.mock import patch, MagicMock

from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.user import User


def test_verify_account_dispatches_task(monkeypatch, client):
    """Verify endpoint dispatches a Celery task and returns 200 immediately."""
    with SessionLocal() as db:
        user = User(telegram_id=1111, username="owner")
        db.add(user)
        db.commit()
        db.refresh(user)

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=999,
            phone_e164="+10000000099",
            status=TelegramAccountStatus.active,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

    token = create_access_token(str(user.id))

    # Mock the Celery verify task
    dispatched = []
    mock_task = MagicMock()
    mock_task.delay = lambda *args: dispatched.append(args)
    monkeypatch.setattr(
        "app.api.v1.tg_accounts.verify_account_task",
        mock_task,
    )

    response = client.post(
        f"/api/v1/tg-accounts/{account.id}/verify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_200_OK
