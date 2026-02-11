from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.account import Account, AccountStatus
from app.models.user import User


class DummyMe:
    def __init__(self):
        self.id = 12345
        self.username = "verified_user"
        self.first_name = "Verified"


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get_me(self):
        return DummyMe()


def test_verify_account_dispatches_task(monkeypatch, client):
    """Legacy verify endpoint now dispatches to Celery and returns 200 immediately."""
    with SessionLocal() as db:
        user = User(telegram_id=1111, username="owner")
        db.add(user)
        db.commit()
        db.refresh(user)

        account = Account(
            user_id=user.id,
            owner_id=user.id,
            telegram_id=999,
            status=AccountStatus.new,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

    token = create_access_token(str(user.id))

    # Mock the Celery task dispatch
    dispatched = []
    monkeypatch.setattr(
        "app.api.v1.accounts.legacy_verify_account",
        type("FakeTask", (), {
            "name": "legacy_verify_account",
            "delay": lambda self, *args: dispatched.append(args),
        })(),
    )

    response = client.post(
        f"/api/v1/accounts/{account.id}/verify",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["needs_password"] is False
    # Task was dispatched
    assert len(dispatched) == 1
    assert dispatched[0] == (account.id,)
