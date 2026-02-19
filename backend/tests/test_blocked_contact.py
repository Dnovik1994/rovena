import asyncio

from pyrogram.errors import UserBlocked

from app.core.database import SessionLocal
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.campaign import Campaign, CampaignStatus
from app.models.contact import Contact
from app.models.project import Project
from app.models.target import Target, TargetType
from app.models.user import User
from app.workers import tasks


class DummyClient:
    def __init__(self, error=None):
        self.error = error

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def add_chat_members(self, _target, _members):
        if self.error:
            raise self.error
        return True


def _setup_campaign() -> Campaign:
    with SessionLocal() as db:
        user = User(telegram_id=9001, username="owner", first_name="Owner")
        db.add(user)
        db.commit()
        db.refresh(user)

        project = Project(owner_id=user.id, name="Project", description=None)
        db.add(project)
        db.commit()
        db.refresh(project)

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=9002,
            phone_e164="+10000009002",
            status=TelegramAccountStatus.active,
        )
        db.add(account)

        contact = Contact(
            project_id=project.id,
            owner_id=user.id,
            source_id=None,
            telegram_id=9003,
            username="contact",
            first_name="Contact",
        )
        db.add(contact)

        target = Target(
            project_id=project.id,
            owner_id=user.id,
            name="Target",
            link="https://t.me/test",
            type=TargetType.group,
        )
        db.add(target)
        db.commit()
        db.refresh(target)

        campaign = Campaign(
            project_id=project.id,
            owner_id=user.id,
            source_id=None,
            target_id=target.id,
            name="Invite",
            status=CampaignStatus.active,
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        return campaign


def test_contact_blocked_event(monkeypatch, client):
    campaign = _setup_campaign()
    events = []

    monkeypatch.setattr(tasks, "create_tg_account_client", lambda *_args, **_kwargs: DummyClient(UserBlocked()))
    monkeypatch.setattr(tasks.manager, "broadcast_sync", lambda payload: events.append(payload))

    async def _sleep(_value):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)

    asyncio.run(tasks._run_campaign_dispatch(campaign.id))

    with SessionLocal() as db:
        contact = db.query(Contact).first()
        assert contact.blocked is True
        assert contact.blocked_reason == "UserBlocked"

    assert any(event["type"] == "contact_blocked" for event in events)
