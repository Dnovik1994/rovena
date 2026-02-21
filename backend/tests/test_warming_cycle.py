"""Tests for _run_tg_warming_cycle, check_tg_cooldowns, resume_tg_warming."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pyrogram.errors import AuthKeyUnregistered, FloodWait, UserDeactivatedBan

from app.models.telegram_account import TelegramAccountStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(
    *,
    account_id=1,
    status=TelegramAccountStatus.warming,
    warming_day=1,
    warming_started_at=None,
    warming_joined_channels=None,
    warming_actions_completed=0,
    target_warming_actions=10,
    cooldown_until=None,
    flood_wait_at=None,
    owner_user_id=1,
    phone_e164="+380501234567",
    proxy_id=None,
    last_error=None,
    warming_task_id=None,
    warming_task_started_at=None,
):
    acc = MagicMock()
    acc.id = account_id
    acc.status = status
    acc.warming_day = warming_day
    acc.warming_started_at = warming_started_at
    acc.warming_joined_channels = warming_joined_channels
    acc.warming_actions_completed = warming_actions_completed
    acc.target_warming_actions = target_warming_actions
    acc.cooldown_until = cooldown_until
    acc.flood_wait_at = flood_wait_at
    acc.owner_user_id = owner_user_id
    acc.phone_e164 = phone_e164
    acc.proxy_id = proxy_id
    acc.last_error = last_error
    acc.warming_task_id = warming_task_id
    acc.warming_task_started_at = warming_task_started_at
    return acc


def _mock_db(account):
    """Create a MagicMock DB session that returns `account` from db.get(...)."""
    db = MagicMock()
    db.get.return_value = account
    return db


def _patch_session_local(db_mock):
    """Return a patch for SessionLocal that yields db_mock."""
    return patch(
        "app.workers.tg_warming_tasks.SessionLocal",
        return_value=db_mock,
    )


def _make_async_client():
    """Create a mock async Telegram client."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


def _make_db_context_manager(db_session):
    """Create a context-manager mock for `with SessionLocal() as db:`."""
    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=db_session)
    cm.__exit__ = MagicMock(return_value=False)
    return cm


# ---------------------------------------------------------------------------
# _run_tg_warming_cycle tests
# ---------------------------------------------------------------------------


async def test_rest_period_skips():
    """warming_day=0, rest_until in future → return without actions."""
    future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    account = _make_account(
        warming_day=0,
        warming_joined_channels={"rest_until": future, "channels": [], "done_once": []},
    )
    db = _mock_db(account)

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    # Should not increment day — still resting
    assert account.warming_day == 0


async def test_rest_period_ends():
    """warming_day=0, rest_until in past → day becomes 1."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    account = _make_account(
        warming_day=0,
        warming_joined_channels={"rest_until": past, "channels": [], "done_once": []},
    )
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, return_value=True), \
         patch("app.workers.tg_warming_tasks.asyncio.sleep", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    # Day: 0 → 1 (rest end) → 2 (after success)
    assert account.warming_day == 2


async def test_day_increments_after_success():
    """After successful plan execution, warming_day += 1."""
    account = _make_account(warming_day=5)
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, return_value=True), \
         patch("app.workers.tg_warming_tasks.asyncio.sleep", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.warming_day == 6


async def test_day_15_becomes_active():
    """warming_day=14 after success → day=15 → status=active (no recent flood)."""
    account = _make_account(warming_day=14, flood_wait_at=None)
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, return_value=True), \
         patch("app.workers.tg_warming_tasks.asyncio.sleep", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.warming_day == 15
    assert account.status == TelegramAccountStatus.active


async def test_flood_wait_rolls_back_3_days():
    """FloodWait → warming_day -= 3, min 1."""
    account = _make_account(warming_day=7)
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, side_effect=FloodWait(value=300)), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.warming_day == 4  # 7 - 3 = 4
    assert account.status == TelegramAccountStatus.cooldown


async def test_flood_wait_rolls_back_min_1():
    """FloodWait on day 2 → warming_day = max(1, 2-3) = 1."""
    account = _make_account(warming_day=2)
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, side_effect=FloodWait(value=100)), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.warming_day == 1  # max(1, 2-3) = 1


async def test_flood_wait_sends_notification():
    """FloodWait → send_notification is called."""
    account = _make_account(warming_day=5)
    db = _mock_db(account)
    mock_client = _make_async_client()
    mock_notify = AsyncMock()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, side_effect=FloodWait(value=300)), \
         patch("app.workers.tg_warming_tasks._send_notification", mock_notify), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    mock_notify.assert_called_once()
    assert mock_notify.call_args[0][0] == "flood_wait"


async def test_banned_sets_status_and_notifies():
    """UserDeactivatedBan → status=banned + notification."""
    account = _make_account(warming_day=3)
    db = _mock_db(account)
    mock_client = _make_async_client()
    mock_notify = AsyncMock()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, side_effect=UserDeactivatedBan()), \
         patch("app.workers.tg_warming_tasks._send_notification", mock_notify), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.status == TelegramAccountStatus.banned
    mock_notify.assert_called_once()
    assert mock_notify.call_args[0][0] == "account_banned"


async def test_generic_error_sets_cooldown():
    """Generic Exception → cooldown 1 hour (NOT error status)."""
    account = _make_account(warming_day=4)
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, side_effect=RuntimeError("oops")), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.status == TelegramAccountStatus.cooldown
    assert account.cooldown_until is not None
    assert account.status != TelegramAccountStatus.error


async def test_quiet_hours_skips():
    """In quiet hours → start_tg_warming returns immediately."""
    from app.workers.tg_warming_tasks import start_tg_warming

    with patch("app.workers.tg_warming_tasks.is_quiet_hours", return_value=True):
        # Celery bind=True: __wrapped__ is already bound, call without self
        result = start_tg_warming.run(1)

    assert result is None


async def test_not_warming_status_skips():
    """Account not in warming status → skip."""
    account = _make_account(status=TelegramAccountStatus.active, warming_day=5)
    db = _mock_db(account)

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    db.commit.assert_not_called()


async def test_account_not_found_returns():
    """Account not found in DB → return gracefully."""
    db = MagicMock()
    db.get.return_value = None

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(999)

    db.commit.assert_not_called()


async def test_auth_key_unregistered_sets_banned():
    """AuthKeyUnregistered → status=banned."""
    account = _make_account(warming_day=3)
    db = _mock_db(account)
    mock_client = _make_async_client()

    with _patch_session_local(db), \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.create_tg_account_client", return_value=mock_client), \
         patch("app.workers.tg_warming_tasks._safe_action", new_callable=AsyncMock, side_effect=AuthKeyUnregistered()), \
         patch("app.workers.tg_warming_tasks._send_notification", new_callable=AsyncMock), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import _run_tg_warming_cycle
        await _run_tg_warming_cycle(account.id)

    assert account.status == TelegramAccountStatus.banned


# ---------------------------------------------------------------------------
# check_tg_cooldowns tests
# ---------------------------------------------------------------------------


def test_cooldown_expired_day_15_no_flood_becomes_active():
    """warming_day>=15 + no recent flood → active."""
    account = _make_account(
        warming_day=15,
        status=TelegramAccountStatus.cooldown,
        cooldown_until=datetime.now(timezone.utc) - timedelta(minutes=5),
        flood_wait_at=None,
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_expired", return_value=True), \
         patch("app.workers.tg_warming_tasks._broadcast_warming_update"), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import check_tg_cooldowns
        check_tg_cooldowns.run()

    assert account.status == TelegramAccountStatus.active
    assert account.cooldown_until is None
    assert account.last_error is None


def test_cooldown_expired_day_10_becomes_warming():
    """warming_day=10 → warming."""
    account = _make_account(
        warming_day=10,
        status=TelegramAccountStatus.cooldown,
        cooldown_until=datetime.now(timezone.utc) - timedelta(minutes=5),
        flood_wait_at=None,
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_expired", return_value=True), \
         patch("app.workers.tg_warming_tasks._broadcast_warming_update"), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import check_tg_cooldowns
        check_tg_cooldowns.run()

    assert account.status == TelegramAccountStatus.warming


def test_cooldown_expired_day_15_recent_flood_stays_warming():
    """warming_day>=15 + recent flood_wait_at → warming (not active)."""
    now = datetime.now(timezone.utc)
    account = _make_account(
        warming_day=15,
        status=TelegramAccountStatus.cooldown,
        cooldown_until=now - timedelta(minutes=5),
        flood_wait_at=now - timedelta(days=2),  # recent flood < 14 days ago
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.filter.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_expired", return_value=True), \
         patch("app.workers.tg_warming_tasks._broadcast_warming_update"), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        from app.workers.tg_warming_tasks import check_tg_cooldowns
        check_tg_cooldowns.run()

    assert account.status == TelegramAccountStatus.warming


# ---------------------------------------------------------------------------
# resume_tg_warming tests
# ---------------------------------------------------------------------------


def test_resume_skips_resting_accounts():
    """warming_day=0, rest_until in future → skip (no dispatch)."""
    future = (datetime.now(timezone.utc) + timedelta(hours=24)).isoformat()
    account = _make_account(
        warming_day=0,
        warming_joined_channels={"rest_until": future, "channels": [], "done_once": []},
        cooldown_until=None,
        warming_task_id=None,
        warming_task_started_at=None,
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    mock_delay = MagicMock()

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_quiet_hours", return_value=False), \
         patch("app.workers.tg_warming_tasks._get_max_concurrent", return_value=10), \
         patch("app.workers.tg_warming_tasks.start_tg_warming") as mock_task, \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        mock_task.delay = mock_delay
        from app.workers.tg_warming_tasks import resume_tg_warming
        resume_tg_warming.run()

    mock_delay.assert_not_called()


def test_resume_transitions_day0_to_day1():
    """rest_until in past → day=1, dispatch."""
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    account = _make_account(
        warming_day=0,
        warming_joined_channels={"rest_until": past, "channels": [], "done_once": []},
        cooldown_until=None,
        warming_task_id=None,
        warming_task_started_at=None,
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    mock_delay = MagicMock()

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_quiet_hours", return_value=False), \
         patch("app.workers.tg_warming_tasks._get_max_concurrent", return_value=10), \
         patch("app.workers.tg_warming_tasks.start_tg_warming") as mock_task, \
         patch("app.workers.tg_warming_tasks._broadcast_account_update"), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        mock_task.delay = mock_delay
        from app.workers.tg_warming_tasks import resume_tg_warming
        resume_tg_warming.run()

    assert account.warming_day == 1
    mock_delay.assert_called_once_with(account.id)


def test_resume_quiet_hours_skips():
    """Quiet hours active → return without dispatching."""
    from app.workers.tg_warming_tasks import resume_tg_warming

    with patch("app.workers.tg_warming_tasks.is_quiet_hours", return_value=True), \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        resume_tg_warming.run()


def test_resume_skips_active_lease():
    """Account with active warming lease → skip."""
    now = datetime.now(timezone.utc)
    account = _make_account(
        warming_day=5,
        cooldown_until=None,
        warming_task_id="some-task-id",
        warming_task_started_at=now - timedelta(minutes=10),  # within 90min TTL
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    mock_delay = MagicMock()

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_quiet_hours", return_value=False), \
         patch("app.workers.tg_warming_tasks._get_max_concurrent", return_value=10), \
         patch("app.workers.tg_warming_tasks.start_tg_warming") as mock_task, \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        mock_task.delay = mock_delay
        from app.workers.tg_warming_tasks import resume_tg_warming
        resume_tg_warming.run()

    mock_delay.assert_not_called()


def test_resume_dispatches_ready_account():
    """Account with warming_day > 0, no lease, no cooldown → dispatch."""
    account = _make_account(
        warming_day=5,
        cooldown_until=None,
        warming_task_id=None,
        warming_task_started_at=None,
    )

    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.limit.return_value.all.return_value = [account]
    cm = _make_db_context_manager(mock_session)

    mock_delay = MagicMock()

    with patch("app.workers.tg_warming_tasks.SessionLocal", return_value=cm), \
         patch("app.workers.tg_warming_tasks.is_quiet_hours", return_value=False), \
         patch("app.workers.tg_warming_tasks._get_max_concurrent", return_value=10), \
         patch("app.workers.tg_warming_tasks.start_tg_warming") as mock_task, \
         patch("app.workers.tg_warming_tasks.sentry_sdk"):
        mock_task.delay = mock_delay
        from app.workers.tg_warming_tasks import resume_tg_warming
        resume_tg_warming.run()

    mock_delay.assert_called_once_with(account.id)
