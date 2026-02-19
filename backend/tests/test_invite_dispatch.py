"""Infrastructure + smoke test for InviteCampaign dispatch (task #16)."""

from __future__ import annotations

import asyncio
import random
import types
from datetime import datetime, timezone

import pytest
import sentry_sdk
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.invite_campaign import InviteCampaign, InviteCampaignStatus
from app.models.invite_task import InviteTask, InviteTaskStatus
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.tg_user import TgUser
from app.models.user import User
from app.workers import tg_invite_tasks
from app.workers.tg_invite_tasks import _run_invite_campaign_dispatch


# ---------------------------------------------------------------------------
# DummyInviteClient
# ---------------------------------------------------------------------------

class _DummyChat:
    """Minimal object returned by join_chat / get_chat."""

    def __init__(self, chat_id: int = -1001234567890):
        self.id = chat_id


class DummyInviteClient:
    """Fake pyrogram.Client with configurable per-method side effects.

    ``side_effect`` for each method can be:
    - ``None``          → always succeeds
    - ``Exception``     → always raises that exception
    - ``list[E | None]`` → pops from list per call; when exhausted → success
    """

    def __init__(self, *, target_chat_id: int = -1001234567890):
        self.target_chat_id = target_chat_id

        # Per-method side effects (None | Exception | list)
        self.add_chat_members_side_effect: Exception | list | None = None
        self.join_chat_side_effect: Exception | list | None = None
        self.get_chat_side_effect: Exception | list | None = None
        self.get_users_side_effect: Exception | list | None = None

        # Call counters
        self.add_chat_members_calls: int = 0
        self.join_chat_calls: int = 0
        self.get_chat_calls: int = 0
        self.get_users_calls: int = 0

    # -- context manager -----------------------------------------------------

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    # -- helpers --------------------------------------------------------------

    def _next_effect(self, method: str) -> Exception | None:
        effects = getattr(self, f"{method}_side_effect")
        if effects is None:
            return None
        if isinstance(effects, list):
            return effects.pop(0) if effects else None
        return effects  # single Exception — always raise

    # -- Telegram API stubs ---------------------------------------------------

    async def add_chat_members(self, chat_id, user_ids):
        self.add_chat_members_calls += 1
        effect = self._next_effect("add_chat_members")
        if effect is not None:
            raise effect
        return True

    async def join_chat(self, link):
        self.join_chat_calls += 1
        effect = self._next_effect("join_chat")
        if effect is not None:
            raise effect
        return _DummyChat(self.target_chat_id)

    async def get_chat(self, username):
        self.get_chat_calls += 1
        effect = self._next_effect("get_chat")
        if effect is not None:
            raise effect
        return _DummyChat(self.target_chat_id)

    async def get_users(self, user_id):
        self.get_users_calls += 1
        effect = self._next_effect("get_users")
        if effect is not None:
            raise effect
        return True


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

_seq = 0


def _next_seq() -> int:
    global _seq
    _seq += 1
    return _seq


def create_test_user(db: Session) -> User:
    seq = _next_seq()
    user = User(telegram_id=100_000 + seq, username=f"user_{seq}", first_name=f"User{seq}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_tg_account(
    db: Session,
    owner_id: int,
    *,
    status: TelegramAccountStatus = TelegramAccountStatus.active,
) -> TelegramAccount:
    seq = _next_seq()
    account = TelegramAccount(
        owner_user_id=owner_id,
        tg_user_id=200_000 + seq,
        phone_e164=f"+1{seq:010d}",
        status=status,
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def create_test_invite_campaign(
    db: Session,
    owner_id: int,
    *,
    status: InviteCampaignStatus = InviteCampaignStatus.active,
    target_chat_id: int = -1001234567890,
    max_invites_total: int = 100,
    invites_per_hour_per_account: int = 30,
    max_accounts: int = 5,
) -> InviteCampaign:
    seq = _next_seq()
    campaign = InviteCampaign(
        owner_id=owner_id,
        name=f"Campaign_{seq}",
        status=status,
        target_chat_id=target_chat_id,
        max_invites_total=max_invites_total,
        invites_per_hour_per_account=invites_per_hour_per_account,
        max_accounts=max_accounts,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return campaign


def create_test_tg_user(db: Session, telegram_id: int) -> TgUser:
    tg_user = TgUser(telegram_id=telegram_id)
    db.add(tg_user)
    db.commit()
    db.refresh(tg_user)
    return tg_user


def create_test_invite_task(
    db: Session,
    campaign_id: int,
    tg_user_id: int,
    *,
    status: InviteTaskStatus = InviteTaskStatus.pending,
) -> InviteTask:
    task = InviteTask(
        campaign_id=campaign_id,
        tg_user_id=tg_user_id,
        status=status,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


# ---------------------------------------------------------------------------
# patch_dispatch fixture
# ---------------------------------------------------------------------------

async def _noop_sleep(_seconds):
    return None


@pytest.fixture()
def patch_dispatch(monkeypatch):
    """Patch all external dependencies of invite campaign dispatch.

    Returns a namespace with:
    - ``client``: the DummyInviteClient instance (configure side_effects before calling dispatch)
    - ``reschedule_calls``: list of captured ``apply_async`` calls
    - ``sentry_calls``: list of captured ``sentry_sdk.capture_exception`` calls
    """
    dummy_client = DummyInviteClient()
    reschedule_calls: list = []
    sentry_calls: list = []

    monkeypatch.setattr(
        tg_invite_tasks, "create_tg_account_client",
        lambda *_args, **_kwargs: dummy_client,
    )
    monkeypatch.setattr(asyncio, "sleep", _noop_sleep)
    monkeypatch.setattr(random, "uniform", lambda _a, _b: 1.0)
    monkeypatch.setattr(sentry_sdk, "capture_exception", lambda exc: sentry_calls.append(exc))
    monkeypatch.setattr(
        tg_invite_tasks.invite_campaign_dispatch, "apply_async",
        lambda *args, **kwargs: reschedule_calls.append({"args": args, "kwargs": kwargs}),
    )

    return types.SimpleNamespace(
        client=dummy_client,
        reschedule_calls=reschedule_calls,
        sentry_calls=sentry_calls,
    )


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------


def test_smoke_single_task_completed(patch_dispatch):
    """One pending task → dispatch → task=success, campaign=completed."""
    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=300_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id
        task_id = task.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.success
        assert task.completed_at is not None

        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.completed
        assert campaign.invites_completed == 1
        assert campaign.completed_at is not None

    # Verify the dummy client was actually called
    assert patch_dispatch.client.add_chat_members_calls == 1
    assert patch_dispatch.client.get_users_calls == 1
    # No reschedule needed — all tasks done
    assert len(patch_dispatch.reschedule_calls) == 0
