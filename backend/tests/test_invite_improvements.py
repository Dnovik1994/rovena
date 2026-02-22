"""Tests for invite campaign improvements (Stage B).

Covers:
- warmup check filtering
- cross-campaign dedup
- already-member filtering
- orphan cleanup
- batch size limit
- ban handling
- websocket broadcast on success
- campaign completed notification
"""

from __future__ import annotations

import asyncio
import random
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
import sentry_sdk
from pyrogram.errors import UserBannedInChannel
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models.invite_campaign import InviteCampaign, InviteCampaignStatus
from app.models.invite_task import InviteTask, InviteTaskStatus
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.tg_chat_member import TgChatMember
from app.models.tg_user import TgUser
from app.models.user import User
from app.workers import tg_invite_tasks
from app.workers.tg_invite_tasks import (
    _run_invite_campaign_dispatch,
    cleanup_orphan_invite_tasks,
)

# Re-use helpers from test_invite_dispatch
from tests.test_invite_dispatch import (
    DummyInviteClient,
    create_test_invite_campaign,
    create_test_invite_task,
    create_test_tg_account,
    create_test_tg_user,
    create_test_user,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

async def _noop_sleep(_seconds):
    return None


@pytest.fixture()
def patch_dispatch(monkeypatch):
    """Patch external deps for invite dispatch tests."""
    dummy_client = DummyInviteClient()
    reschedule_calls: list = []
    sentry_calls: list = []
    broadcast_calls: list = []
    notification_calls: list = []

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

    # Capture WebSocket broadcasts
    from app.services.websocket_manager import manager
    monkeypatch.setattr(manager, "broadcast_sync", lambda payload: broadcast_calls.append(payload))

    # Capture notification calls
    monkeypatch.setattr(
        tg_invite_tasks, "send_notification_sync",
        lambda event_type, message: notification_calls.append({"event_type": event_type, "message": message}),
    )

    return types.SimpleNamespace(
        client=dummy_client,
        reschedule_calls=reschedule_calls,
        sentry_calls=sentry_calls,
        broadcast_calls=broadcast_calls,
        notification_calls=notification_calls,
    )


# ---------------------------------------------------------------------------
# 1. test_warmup_check_filters_unwarmed
# ---------------------------------------------------------------------------

def test_warmup_check_filters_unwarmed(patch_dispatch):
    """Account with warming_day=5 is NOT picked for invite dispatch."""
    with SessionLocal() as db:
        user = create_test_user(db)
        # Account is active but only warming_day=5 (needs >=15)
        account = create_test_tg_account(db, user.id, warming_day=5)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=2_000_001)
        create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    # Account was not used — campaign should be marked as error (no warmed-up accounts)
    with SessionLocal() as db:
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.error

    # Client should never have been called
    assert patch_dispatch.client.add_chat_members_calls == 0


# ---------------------------------------------------------------------------
# 2. test_cross_campaign_dedup
# ---------------------------------------------------------------------------

def test_cross_campaign_dedup(patch_dispatch):
    """Contact already success in another campaign with same target → excluded from new campaign."""
    TARGET_CHAT_ID = -1001234567890

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)

        # Create source chat setup (TgAccountChat + TgChatMember)
        from app.models.tg_account_chat import TgAccountChat
        source_chat = TgAccountChat(
            account_id=account.id,
            chat_id=-100999,
            title="Source Chat",
            chat_type="supergroup",
            is_admin=False,
            is_creator=False,
        )
        db.add(source_chat)
        db.flush()

        # Target chat (admin)
        target_chat = TgAccountChat(
            account_id=account.id,
            chat_id=TARGET_CHAT_ID,
            title="Target Chat",
            chat_type="supergroup",
            is_admin=True,
            is_creator=False,
        )
        db.add(target_chat)
        db.flush()

        # Create tg_users
        tg_user_already = create_test_tg_user(db, telegram_id=2_100_001)
        tg_user_new = create_test_tg_user(db, telegram_id=2_100_002)

        # Add both to source chat
        db.add(TgChatMember(chat_id=-100999, user_id=tg_user_already.id))
        db.add(TgChatMember(chat_id=-100999, user_id=tg_user_new.id))
        db.commit()

        # OLD campaign — tg_user_already was successfully invited
        old_campaign = InviteCampaign(
            owner_id=user.id,
            name="OldCampaign",
            status=InviteCampaignStatus.completed,
            target_chat_id=TARGET_CHAT_ID,
            max_invites_total=100,
        )
        db.add(old_campaign)
        db.flush()
        db.add(InviteTask(
            campaign_id=old_campaign.id,
            tg_user_id=tg_user_already.id,
            status=InviteTaskStatus.success,
        ))
        db.commit()

        # Now create a NEW campaign via the API endpoint
        from app.api.v1.invite_campaigns import create_invite_campaign
        from app.schemas.invite_campaign import InviteCampaignCreate

        payload = InviteCampaignCreate(
            name="NewCampaign",
            source_chat_id=-100999,
            target_chat_id=TARGET_CHAT_ID,
            max_invites_total=100,
        )

        # Mock the current user dependency
        result = create_invite_campaign(payload=payload, current_user=user, db=db)

        # Only one task should be created (tg_user_new), NOT tg_user_already
        assert result.total_tasks == 1

        new_campaign_id = result.id
        tasks = db.query(InviteTask).filter(InviteTask.campaign_id == new_campaign_id).all()
        assert len(tasks) == 1
        assert tasks[0].tg_user_id == tg_user_new.id


# ---------------------------------------------------------------------------
# 3. test_already_member_filtered
# ---------------------------------------------------------------------------

def test_already_member_filtered(patch_dispatch):
    """Contact already in target group (TgChatMember) → excluded from campaign tasks."""
    TARGET_CHAT_ID = -1001234567890

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)

        from app.models.tg_account_chat import TgAccountChat

        # Source chat
        source_chat = TgAccountChat(
            account_id=account.id,
            chat_id=-100888,
            title="Source",
            chat_type="supergroup",
            is_admin=False,
            is_creator=False,
        )
        db.add(source_chat)

        # Target chat (admin)
        target_chat = TgAccountChat(
            account_id=account.id,
            chat_id=TARGET_CHAT_ID,
            title="Target",
            chat_type="supergroup",
            is_admin=True,
            is_creator=False,
        )
        db.add(target_chat)
        db.flush()

        # Create users
        tg_user_member = create_test_tg_user(db, telegram_id=2_200_001)
        tg_user_not_member = create_test_tg_user(db, telegram_id=2_200_002)

        # Both in source chat
        db.add(TgChatMember(chat_id=-100888, user_id=tg_user_member.id))
        db.add(TgChatMember(chat_id=-100888, user_id=tg_user_not_member.id))

        # tg_user_member is ALSO already in target group
        db.add(TgChatMember(chat_id=TARGET_CHAT_ID, user_id=tg_user_member.id))
        db.commit()

        from app.api.v1.invite_campaigns import create_invite_campaign
        from app.schemas.invite_campaign import InviteCampaignCreate

        payload = InviteCampaignCreate(
            name="FilterTest",
            source_chat_id=-100888,
            target_chat_id=TARGET_CHAT_ID,
            max_invites_total=100,
        )

        result = create_invite_campaign(payload=payload, current_user=user, db=db)

        # Only tg_user_not_member should be included
        assert result.total_tasks == 1

        new_campaign_id = result.id
        tasks = db.query(InviteTask).filter(InviteTask.campaign_id == new_campaign_id).all()
        assert len(tasks) == 1
        assert tasks[0].tg_user_id == tg_user_not_member.id


# ---------------------------------------------------------------------------
# 4. test_orphan_cleanup
# ---------------------------------------------------------------------------

def test_orphan_cleanup():
    """in_progress task older than 15 min → returned to pending by cleanup."""
    with SessionLocal() as db:
        user = create_test_user(db)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=2_300_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id, status=InviteTaskStatus.in_progress)

        # Set attempted_at to 20 minutes ago (> 15 min cutoff)
        task.attempted_at = datetime.now(timezone.utc) - timedelta(minutes=20)
        task.account_id = 999  # arbitrary
        db.commit()
        task_id = task.id

    # Run the cleanup task function directly (bypass Celery)
    cleanup_orphan_invite_tasks()

    with SessionLocal() as db:
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.pending
        assert task.account_id is None
        assert task.attempted_at is None


# ---------------------------------------------------------------------------
# 5. test_batch_size_limit
# ---------------------------------------------------------------------------

def test_batch_size_limit(patch_dispatch):
    """With available_slots=10, batch size is capped at 3 per dispatch round."""
    with SessionLocal() as db:
        user = create_test_user(db)
        # invites_per_hour=10 and no invites yet → available_slots=10
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(
            db, user.id,
            invites_per_hour_per_account=10,
            max_invites_total=20,
        )
        campaign_id = campaign.id

        # Create 10 pending tasks
        for i in range(10):
            tg_user = create_test_tg_user(db, telegram_id=2_400_001 + i)
            create_test_invite_task(db, campaign.id, tg_user.id)

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # Only 3 tasks should have been processed (batch_size = min(3, 10) = 3)
        success_count = (
            db.query(InviteTask)
            .filter(InviteTask.campaign_id == campaign_id, InviteTask.status == InviteTaskStatus.success)
            .count()
        )
        assert success_count == 3

        # 7 tasks should still be pending
        pending_count = (
            db.query(InviteTask)
            .filter(InviteTask.campaign_id == campaign_id, InviteTask.status == InviteTaskStatus.pending)
            .count()
        )
        assert pending_count == 7

    # Client was called exactly 3 times
    assert patch_dispatch.client.add_chat_members_calls == 3

    # Campaign should be rescheduled (pending tasks remain)
    assert len(patch_dispatch.reschedule_calls) == 1


# ---------------------------------------------------------------------------
# 6. test_ban_handling
# ---------------------------------------------------------------------------

def test_ban_handling(patch_dispatch):
    """UserBannedInChannel → account cooldown 24h, task failed."""
    patch_dispatch.client.add_chat_members_side_effect = UserBannedInChannel()

    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=2_500_001)
        task = create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id
        task_id = task.id
        account_id = account.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    with SessionLocal() as db:
        # Task should be failed
        task = db.get(InviteTask, task_id)
        assert task.status == InviteTaskStatus.failed
        assert task.error_message == "UserBannedInChannel"

        # Account should be in cooldown for ~24 hours
        account = db.get(TelegramAccount, account_id)
        assert account.status == TelegramAccountStatus.cooldown
        assert account.cooldown_until is not None
        # Check cooldown is approximately 24 hours from now
        expected_cooldown = datetime.now(timezone.utc) + timedelta(hours=24)
        if account.cooldown_until.tzinfo is None:
            cooldown = account.cooldown_until.replace(tzinfo=timezone.utc)
        else:
            cooldown = account.cooldown_until
        diff = abs((cooldown - expected_cooldown).total_seconds())
        assert diff < 60, f"Cooldown should be ~24h, diff={diff}s"

        # last_error should mention ban
        assert "Banned in target" in account.last_error

    # Sentry captured the exception
    assert len(patch_dispatch.sentry_calls) == 1


# ---------------------------------------------------------------------------
# 7. test_websocket_broadcast_on_success
# ---------------------------------------------------------------------------

def test_websocket_broadcast_on_success(patch_dispatch):
    """Successful invite → broadcast is called with invite_campaign_progress."""
    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=2_600_001)
        create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    # Should have progress broadcast + completed broadcast
    progress_broadcasts = [
        b for b in patch_dispatch.broadcast_calls
        if b.get("type") == "invite_campaign_progress"
    ]
    assert len(progress_broadcasts) >= 1
    assert progress_broadcasts[0]["campaign_id"] == campaign_id

    completed_broadcasts = [
        b for b in patch_dispatch.broadcast_calls
        if b.get("type") == "invite_campaign_completed"
    ]
    assert len(completed_broadcasts) == 1


# ---------------------------------------------------------------------------
# 8. test_campaign_completed_notification
# ---------------------------------------------------------------------------

def test_campaign_completed_notification(patch_dispatch):
    """Campaign completion → send_notification_sync is called."""
    with SessionLocal() as db:
        user = create_test_user(db)
        account = create_test_tg_account(db, user.id)
        campaign = create_test_invite_campaign(db, user.id)
        tg_user = create_test_tg_user(db, telegram_id=2_700_001)
        create_test_invite_task(db, campaign.id, tg_user.id)
        campaign_id = campaign.id

    asyncio.run(_run_invite_campaign_dispatch(campaign_id))

    # Campaign should be completed
    with SessionLocal() as db:
        campaign = db.get(InviteCampaign, campaign_id)
        assert campaign.status == InviteCampaignStatus.completed

    # Notification should have been sent
    assert len(patch_dispatch.notification_calls) >= 1
    notif = patch_dispatch.notification_calls[0]
    assert notif["event_type"] == "warming_completed"
    assert "Кампания завершена" in notif["message"]
    assert f"ID: {campaign_id}" in notif["message"]
