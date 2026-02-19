import asyncio

from pyrogram.errors import FloodWait

from app.core.database import SessionLocal
from app.clients.device_generator import generate_device_config
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.user import User
from app.workers import tasks


class DummyClient:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


def _create_account(account_status: TelegramAccountStatus, target_actions: int) -> TelegramAccount:
    with SessionLocal() as db:
        user = User(telegram_id=1001, username="tester", first_name="Test")
        db.add(user)
        db.commit()
        db.refresh(user)

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=2001,
            phone_e164="+10000002001",
            status=account_status,
            device_config=generate_device_config(),
            target_warming_actions=target_actions,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account


def test_warming_floodwait(monkeypatch, client):
    account = _create_account(TelegramAccountStatus.warming, target_actions=3)

    monkeypatch.setattr(tasks, "create_tg_account_client", lambda *_args, **_kwargs: DummyClient())

    async def _raise_floodwait(_client):
        raise FloodWait(60)

    monkeypatch.setattr(tasks, "perform_low_risk_action", _raise_floodwait)

    asyncio.run(tasks._run_warming_cycle(account.id))

    with SessionLocal() as db:
        refreshed = db.get(TelegramAccount, account.id)
        assert refreshed.status == TelegramAccountStatus.cooldown
        assert refreshed.cooldown_until is not None


def test_warming_success(monkeypatch, client):
    account = _create_account(TelegramAccountStatus.warming, target_actions=1)

    monkeypatch.setattr(tasks, "create_tg_account_client", lambda *_args, **_kwargs: DummyClient())

    async def _one_action(_client):
        return 1

    monkeypatch.setattr(tasks, "perform_low_risk_action", _one_action)

    asyncio.run(tasks._run_warming_cycle(account.id))

    with SessionLocal() as db:
        refreshed = db.get(TelegramAccount, account.id)
        assert refreshed.status == TelegramAccountStatus.active
        assert refreshed.warming_actions_completed >= 1
