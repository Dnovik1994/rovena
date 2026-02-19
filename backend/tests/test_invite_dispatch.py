"""Infrastructure + smoke test for InviteCampaign dispatch (task #16)."""

from __future__ import annotations

import asyncio
import random
import types
from datetime import datetime, timezone

import pytest
import sentry_sdk
from pyrogram.errors import FloodWait, PeerFlood, UserPrivacyRestricted
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


# ---------------------------------------------------------------------------
# Core test cases — group 1 (happy path + basic errors)
# ---------------------------------------------------------------------------


def test_multiple_tasks_all_completed(patch_dispatch):
    """5 pending tasks → all succeed → campaign completed, invites_completed=5."""
    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        campaign_id = campaign.id

        task_ids = []
        for i in range(5):
            tg_user = create_test_tg_user(db, telegram_id=400_001 + i)
            task = create_test_invite_task(db, campaign.id, tg_user.id)
            task_ids.append(task.id)

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # All 5 tasks should be success
        for tid in task_ids:
            task = db.get(InviteTask, tid)
            assert task.status == InviteTaskStatus.success, f"task {tid} status={task.status}"
            assert task.completed_at is not None

        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.completed
        assert campaign.invites_completed == 5
        assert campaign.completed_at is not None

    assert patch_dispatch.client.add_chat_members_calls == 5
    assert len(patch_dispatch.reschedule_calls) == 0


def test_flood_wait_sets_cooldown_and_reschedules(patch_dispatch):
    """FloodWait(300) on first invite → account cooldown, task reverted, reschedule."""
    patch_dispatch.client.add_chat_members_side_effect = FloodWait(value=300)

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=500_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id
        task_id = task.id
        account_id = account.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # Task should be reverted to pending (not failed)
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.pending

        # Account should be in cooldown
        account = db.get(TelegramAccount, account_id)
        assert account.status == TelegramAccountStatus.cooldown
        assert account.cooldown_until is not None

        # Campaign should NOT be completed (still active, pending task exists)
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.active
        assert campaign.completed_at is None

    # Reschedule must have been called
    assert len(patch_dispatch.reschedule_calls) == 1
    assert patch_dispatch.reschedule_calls[0]["kwargs"]["countdown"] == 60
    # Sentry should capture the exception
    assert len(patch_dispatch.sentry_calls) == 1


def test_peer_flood_fails_task_and_stops_account(patch_dispatch):
    """PeerFlood on first invite → task failed, account stops processing, reschedule.

    NOTE: Current code does NOT set account.status=cooldown for PeerFlood
    (unlike FloodWait).  It only sets account_broke=True internally.
    """
    # 2 tasks: first gets PeerFlood, second should be reverted to pending
    patch_dispatch.client.add_chat_members_side_effect = PeerFlood()

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)

        tg_user1 = create_test_tg_user(db, telegram_id=600_001)
        tg_user2 = create_test_tg_user(db, telegram_id=600_002)
        task1 = create_test_invite_task(db, campaign.id, tg_user1.id)
        task2 = create_test_invite_task(db, campaign.id, tg_user2.id)

        campaign_id = campaign.id
        task1_id = task1.id
        task2_id = task2.id
        account_id = account.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # First task → failed with PeerFlood
        t1 = db.get(InviteTask, task1_id)
        assert t1.status == InviteTaskStatus.failed
        assert t1.error_message == "PeerFlood"

        # Second task → reverted to pending (account_broke stopped processing)
        t2 = db.get(InviteTask, task2_id)
        assert t2.status == InviteTaskStatus.pending

        # Account stays active (PeerFlood does NOT set cooldown in current code)
        account = db.get(TelegramAccount, account_id)
        assert account.status == TelegramAccountStatus.active

        # Campaign invites_failed incremented for the first task
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.invites_failed == 1
        # Campaign NOT completed (pending task remains)
        assert campaign.status != InviteCampaignStatus.completed

    # Reschedule called because pending tasks remain
    assert len(patch_dispatch.reschedule_calls) == 1
    assert len(patch_dispatch.sentry_calls) == 1


def test_user_privacy_restricted_fails_task_others_continue(patch_dispatch):
    """UserPrivacyRestricted on first invite → task failed, remaining succeed.

    3 tasks: first raises UserPrivacyRestricted, others succeed.
    campaign.invites_completed=2, invites_failed=1, status=completed.
    """
    patch_dispatch.client.add_chat_members_side_effect = [
        UserPrivacyRestricted(),  # first call fails
        None,                     # second call succeeds
        None,                     # third call succeeds
    ]

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)

        tg_user1 = create_test_tg_user(db, telegram_id=700_001)
        tg_user2 = create_test_tg_user(db, telegram_id=700_002)
        tg_user3 = create_test_tg_user(db, telegram_id=700_003)
        task1 = create_test_invite_task(db, campaign.id, tg_user1.id)
        task2 = create_test_invite_task(db, campaign.id, tg_user2.id)
        task3 = create_test_invite_task(db, campaign.id, tg_user3.id)

        campaign_id = campaign.id
        task1_id = task1.id
        task2_id = task2.id
        task3_id = task3.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # First task → failed
        t1 = db.get(InviteTask, task1_id)
        assert t1.status == InviteTaskStatus.failed
        assert t1.error_message == "UserPrivacyRestricted"

        # Remaining tasks → success
        t2 = db.get(InviteTask, task2_id)
        assert t2.status == InviteTaskStatus.success
        t3 = db.get(InviteTask, task3_id)
        assert t3.status == InviteTaskStatus.success

        # Campaign counters
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.invites_completed == 2
        assert campaign.invites_failed == 1
        # All tasks resolved → completed
        assert campaign.status == InviteCampaignStatus.completed

    # No reschedule — all tasks done
    assert len(patch_dispatch.reschedule_calls) == 0
    # Sentry captured the privacy error
    assert len(patch_dispatch.sentry_calls) == 1


# ---------------------------------------------------------------------------
# Core test cases — group 2 (lease conflict, non-active campaign, cooldown)
# ---------------------------------------------------------------------------


def test_lease_conflict_skips_dispatch(patch_dispatch, monkeypatch):
    """Campaign locked by another worker → dispatch exits immediately, nothing changes."""

    # SQLite drops timezone info from stored datetimes, so the lease-TTL
    # comparison ``now - campaign.dispatch_started_at`` blows up with
    # "can't subtract offset-naive and offset-aware datetimes".
    # Patch datetime.now() inside the dispatch module to return naive UTC
    # datetimes (matches what SQLite gives back).
    _real_dt = datetime

    class _NaiveNow(_real_dt):
        @classmethod
        def now(cls, tz=None):
            return _real_dt.utcnow()

    monkeypatch.setattr(tg_invite_tasks, "datetime", _NaiveNow)

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=800_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id)

        # Simulate another worker holding the dispatch lease
        campaign.dispatch_task_id = "other-worker-123"
        campaign.dispatch_started_at = datetime.now(timezone.utc)
        db.commit()

        campaign_id = campaign.id
        task_id = task.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # Task must remain pending — dispatch didn't run
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.pending
        assert task.completed_at is None

        # Campaign unchanged
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.active
        assert campaign.dispatch_task_id == "other-worker-123"  # lease untouched

    # No TG API calls at all
    assert patch_dispatch.client.add_chat_members_calls == 0
    assert patch_dispatch.client.get_users_calls == 0
    # No reschedule
    assert len(patch_dispatch.reschedule_calls) == 0


def test_non_active_campaign_skips_dispatch(patch_dispatch):
    """Campaign with status=completed → dispatch does nothing."""
    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(
            db, user.id, status=InviteCampaignStatus.completed,
        )
        tg_user = create_test_tg_user(db, telegram_id=900_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id
        task_id = task.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # Task untouched
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.pending

        # Campaign still completed
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.completed

    # Zero TG API calls
    assert patch_dispatch.client.add_chat_members_calls == 0
    assert len(patch_dispatch.reschedule_calls) == 0


def test_all_accounts_in_cooldown_tasks_stay_pending(patch_dispatch):
    """Only account is in cooldown → no active accounts → tasks stay pending.

    NOTE: Current implementation returns early when no active accounts are
    found (Phase 2) and does NOT reach Phase 4 reschedule logic.  Tasks
    remain pending but no reschedule is triggered.
    """
    with SessionLocal() as db:
        user = create_test_user(db)
        # Account in cooldown — won't be picked by the dispatch query
        account = create_test_tg_account(
            db, user.id, status=TelegramAccountStatus.cooldown,
        )
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=1_000_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id
        task_id = task.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # Task must remain pending — no account could process it
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.pending
        assert task.completed_at is None

        # Campaign stays active
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.active

    # No TG API calls
    assert patch_dispatch.client.add_chat_members_calls == 0
    # No reschedule — early return before Phase 4
    assert len(patch_dispatch.reschedule_calls) == 0
