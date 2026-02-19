import asyncio

from pyrogram.errors import FloodWait

from app.core.database import SessionLocal
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.campaign import Campaign, CampaignStatus
from app.models.contact import Contact
from app.models.project import Project
from app.models.target import Target, TargetType
from app.models.user import User
from app.workers import tasks


class DummyClient:
    def __init__(self, raise_floodwait: bool = False) -> None:
        self.raise_floodwait = raise_floodwait

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def add_chat_members(self, _target, _members):
        if self.raise_floodwait:
            raise FloodWait(30)
        return True


def _setup_campaign(campaign_status: CampaignStatus = CampaignStatus.active) -> Campaign:
    with SessionLocal() as db:
        user = User(telegram_id=5001, username="owner", first_name="Owner")
        db.add(user)
        db.commit()
        db.refresh(user)

        project = Project(owner_id=user.id, name="Project", description=None)
        db.add(project)
        db.commit()
        db.refresh(project)

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=6001,
            phone_e164="+10000006001",
            status=TelegramAccountStatus.active,
        )
        db.add(account)

        contact = Contact(
            project_id=project.id,
            owner_id=user.id,
            source_id=None,
            telegram_id=7001,
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
            status=campaign_status,
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        return campaign


def test_campaign_dispatch_success(monkeypatch, client):
    campaign = _setup_campaign()

    monkeypatch.setattr(tasks, "create_tg_account_client", lambda *_args, **_kwargs: DummyClient())

    async def _sleep(_value):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)

    asyncio.run(tasks._run_campaign_dispatch(campaign.id))

    with SessionLocal() as db:
        refreshed = db.get(Campaign, campaign.id)
        assert refreshed.progress >= 100


def test_campaign_dispatch_floodwait(monkeypatch, client):
    campaign = _setup_campaign()

    monkeypatch.setattr(tasks, "create_tg_account_client", lambda *_args, **_kwargs: DummyClient(True))

    async def _sleep(_value):
        return None

    monkeypatch.setattr(asyncio, "sleep", _sleep)

    asyncio.run(tasks._run_campaign_dispatch(campaign.id))

    with SessionLocal() as db:
        account = db.query(TelegramAccount).filter(TelegramAccount.owner_user_id == campaign.owner_id).first()
        assert account.status == TelegramAccountStatus.cooldown
