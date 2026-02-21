"""Tests for FloodWait throttle: Redis counters, rate calculation, mode transitions."""

from __future__ import annotations

import importlib
import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.telegram_account import TelegramAccountStatus


# ---------------------------------------------------------------------------
# Helper: ensure tg_warming_tasks can be imported even when optional native
# dependencies (e.g. cryptography) are broken in the CI / sandbox environment.
# ---------------------------------------------------------------------------

def _ensure_warming_tasks():
    """Import tg_warming_tasks, stubbing broken native deps if needed."""
    try:
        import app.workers.tg_warming_tasks  # noqa: F811
        return app.workers.tg_warming_tasks
    except (ImportError, Exception):
        pass

    # Stub modules whose native dependencies may be broken in CI/sandbox.
    _stub_modules = [
        "app.clients.telegram_client",
        "app.services.session_crypto",
        "app.services.websocket_manager",
        "app.workers.tg_warming_actions",
        "app.workers.tg_timeout_helpers",
    ]
    for mod_name in _stub_modules:
        if mod_name not in sys.modules:
            sys.modules[mod_name] = MagicMock()

    # Expose names that tg_warming_tasks imports at module level
    sys.modules["app.clients.telegram_client"].TelegramClientDisabledError = type(
        "TelegramClientDisabledError", (Exception,), {}
    )
    sys.modules["app.clients.telegram_client"].create_tg_account_client = MagicMock()
    sys.modules["app.services.websocket_manager"].manager = MagicMock()
    sys.modules["app.workers.tg_warming_actions"]._action_add_contacts = AsyncMock()
    sys.modules["app.workers.tg_warming_actions"]._action_go_online = AsyncMock()
    sys.modules["app.workers.tg_warming_actions"]._action_set_bio = AsyncMock()
    sys.modules["app.workers.tg_warming_actions"]._action_set_name = AsyncMock()
    sys.modules["app.workers.tg_warming_actions"]._action_set_photo = AsyncMock()
    sys.modules["app.workers.tg_warming_actions"]._action_set_username = AsyncMock()
    sys.modules["app.workers.tg_warming_actions"]._action_trusted_conversation = AsyncMock()
    sys.modules["app.workers.tg_timeout_helpers"].collect_async_gen = AsyncMock()
    sys.modules["app.workers.tg_timeout_helpers"].safe_call = AsyncMock()

    # Force (re-)import
    if "app.workers.tg_warming_tasks" in sys.modules:
        del sys.modules["app.workers.tg_warming_tasks"]
    importlib.import_module("app.workers.tg_warming_tasks")

    return sys.modules["app.workers.tg_warming_tasks"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_account(
    *,
    account_id=1,
    status=TelegramAccountStatus.warming,
    warming_day=5,
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


def _make_async_client():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    return mock_client


# ---------------------------------------------------------------------------
# get_flood_rate tests
# ---------------------------------------------------------------------------


def test_flood_rate_zero_when_no_accounts():
    """No warming/cooldown accounts → rate = 0.0."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = "5"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.query.return_value.filter.return_value.count.return_value = 0

    with patch("app.workers.warming_throttle.get_sync_redis_decoded", return_value=mock_redis), \
         patch("app.workers.warming_throttle.SessionLocal", return_value=mock_db):
        from app.workers.warming_throttle import get_flood_rate
        rate = get_flood_rate()

    assert rate == 0.0


def test_flood_rate_calculation():
    """2 floods / 10 warming accounts = 0.2."""
    today_key = f"warming:flood_count:{date.today().isoformat()}"
    mock_redis = MagicMock()
    mock_redis.get.return_value = "2"

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.query.return_value.filter.return_value.count.return_value = 10

    with patch("app.workers.warming_throttle.get_sync_redis_decoded", return_value=mock_redis), \
         patch("app.workers.warming_throttle.SessionLocal", return_value=mock_db):
        from app.workers.warming_throttle import get_flood_rate
        rate = get_flood_rate()

    assert rate == pytest.approx(0.2)
    mock_redis.get.assert_called_once_with(today_key)


# ---------------------------------------------------------------------------
# update_warming_throttle mode transition tests
# ---------------------------------------------------------------------------


def test_throttle_normal_below_5_percent():
    """Flood rate 3% → THROTTLE_NORMAL."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # current mode = normal (default)

    with patch("app.workers.warming_throttle.get_flood_rate", return_value=0.03), \
         patch("app.workers.warming_throttle.get_sync_redis_decoded", return_value=mock_redis), \
         patch("app.workers.warming_throttle.send_notification_sync") as mock_notify:
        from app.workers.warming_throttle import update_warming_throttle
        update_warming_throttle.run()

    # normal → normal: no mode change, no notification
    mock_notify.assert_not_called()
    mock_redis.set.assert_not_called()


def test_throttle_slow_at_10_percent():
    """Flood rate 10% → THROTTLE_SLOW."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = "normal"  # current mode

    with patch("app.workers.warming_throttle.get_flood_rate", return_value=0.10), \
         patch("app.workers.warming_throttle.get_sync_redis_decoded", return_value=mock_redis), \
         patch("app.workers.warming_throttle.send_notification_sync") as mock_notify:
        from app.workers.warming_throttle import update_warming_throttle
        update_warming_throttle.run()

    mock_redis.set.assert_called_once_with("warming:throttle_mode", "slow", ex=3600)
    mock_notify.assert_called_once()
    assert "flood_rate_threshold" in mock_notify.call_args[0]


def test_throttle_paused_above_15_percent():
    """Flood rate 20% → THROTTLE_PAUSED."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = "normal"  # current mode

    with patch("app.workers.warming_throttle.get_flood_rate", return_value=0.20), \
         patch("app.workers.warming_throttle.get_sync_redis_decoded", return_value=mock_redis), \
         patch("app.workers.warming_throttle.send_notification_sync") as mock_notify:
        from app.workers.warming_throttle import update_warming_throttle
        update_warming_throttle.run()

    mock_redis.set.assert_called_once_with("warming:throttle_mode", "paused", ex=3600)
    mock_notify.assert_called_once()


def test_throttle_change_sends_notification():
    """Mode change triggers send_notification_sync with correct event type."""
    mock_redis = MagicMock()
    mock_redis.get.return_value = "slow"  # currently slow

    with patch("app.workers.warming_throttle.get_flood_rate", return_value=0.20), \
         patch("app.workers.warming_throttle.get_sync_redis_decoded", return_value=mock_redis), \
         patch("app.workers.warming_throttle.send_notification_sync") as mock_notify:
        from app.workers.warming_throttle import update_warming_throttle
        update_warming_throttle.run()

    mock_notify.assert_called_once()
    event_type, message = mock_notify.call_args[0]
    assert event_type == "flood_rate_threshold"
    assert "slow" in message
    assert "paused" in message
    assert "20.0%" in message


# ---------------------------------------------------------------------------
# Integration: throttle affects warming cycle
# ---------------------------------------------------------------------------


async def test_paused_mode_skips_warming_cycle():
    """THROTTLE_PAUSED → _run_tg_warming_cycle returns without executing actions."""
    mod = _ensure_warming_tasks()

    account = _make_account(warming_day=5)
    db = MagicMock()
    db.get.return_value = account

    with patch.object(mod, "SessionLocal", return_value=db), \
         patch.object(mod, "_broadcast_account_update"), \
         patch.object(mod, "create_tg_account_client") as mock_create, \
         patch.object(mod, "get_throttle_mode", return_value="paused"), \
         patch.object(mod, "sentry_sdk"):
        await mod._run_tg_warming_cycle(account.id)

    # Client should NOT have been created — we returned before that step
    mock_create.assert_not_called()
    # warming_day should not change
    assert account.warming_day == 5


async def test_slow_mode_doubles_delays():
    """THROTTLE_SLOW → base_delay is multiplied by 2."""
    mod = _ensure_warming_tasks()

    account = _make_account(warming_day=5)
    db = MagicMock()
    db.get.return_value = account
    mock_client = _make_async_client()

    sleep_values: list[float] = []

    async def capture_sleep(val):
        sleep_values.append(val)

    with patch.object(mod, "SessionLocal", return_value=db), \
         patch.object(mod, "_broadcast_account_update"), \
         patch.object(mod, "create_tg_account_client", return_value=mock_client), \
         patch.object(mod, "_safe_action", new_callable=AsyncMock, return_value=True), \
         patch.object(mod, "asyncio") as mock_asyncio, \
         patch.object(mod, "_send_notification", new_callable=AsyncMock), \
         patch.object(mod, "get_throttle_mode", return_value="slow"), \
         patch.object(mod, "increment_flood_counter"), \
         patch.object(mod, "sentry_sdk"):
        mock_asyncio.sleep = AsyncMock(side_effect=capture_sleep)
        await mod._run_tg_warming_cycle(account.id)

    # Day 5 plan has actions after go_online that will sleep.
    # All sleeps (for non-go_online steps) should be >= 30 (15*2 min in slow mode).
    assert len(sleep_values) > 0
    for val in sleep_values:
        assert val >= 30, f"Expected delay >= 30 in slow mode, got {val}"
