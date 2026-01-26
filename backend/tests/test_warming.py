import asyncio

from pyrogram.errors import FloodWait

from app.core.database import SessionLocal
from app.clients.device_generator import generate_device_config
from app.models.account import Account, AccountStatus
from app.models.user import User
from app.workers import tasks


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _create_account(status: AccountStatus, target_actions: int) -> Account:
    with SessionLocal() as db:
        user = User(telegram_id=1001, username="tester", first_name="Test")
        db.add(user)
        db.commit()
        db.refresh(user)

        account = Account(
            user_id=user.id,
            owner_id=user.id,
            telegram_id=2001,
            status=status,
            device_config=generate_device_config(),
            target_warming_actions=target_actions,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account


def test_warming_floodwait(monkeypatch, client):
    account = _create_account(AccountStatus.warming, target_actions=3)

    monkeypatch.setattr(tasks, "get_client", lambda *_args, **_kwargs: DummyClient())

    async def _raise_floodwait(_client):
        raise FloodWait(60)

    monkeypatch.setattr(tasks, "perform_low_risk_action", _raise_floodwait)

    asyncio.run(tasks._run_warming_cycle(account.id))

    with SessionLocal() as db:
        refreshed = db.get(Account, account.id)
        assert refreshed.status == AccountStatus.cooldown
        assert refreshed.cooldown_until is not None


def test_warming_success(monkeypatch, client):
    account = _create_account(AccountStatus.warming, target_actions=1)

    monkeypatch.setattr(tasks, "get_client", lambda *_args, **_kwargs: DummyClient())

    async def _one_action(_client):
        return 1

    monkeypatch.setattr(tasks, "perform_low_risk_action", _one_action)

    asyncio.run(tasks._run_warming_cycle(account.id))

    with SessionLocal() as db:
        refreshed = db.get(Account, account.id)
        assert refreshed.status == AccountStatus.active
        assert refreshed.warming_actions_completed >= 1
