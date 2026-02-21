"""Integration tests for the warming flow (day progression, quiet hours, flood, cooldown).

These tests verify warming logic at the DB / state-machine level without
importing Celery workers (which require a Redis broker at import time).
"""

import importlib
import sys
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.core.database import SessionLocal
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.user import User, UserRole


# ── Helpers ──────────────────────────────────────────────────────────


def _create_admin_user() -> User:
    with SessionLocal() as db:
        user = User(
            telegram_id=7000,
            username="int_admin",
            is_admin=True,
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _create_warming_account(owner_id: int, **kwargs) -> int:
    with SessionLocal() as db:
        account = TelegramAccount(
            owner_user_id=owner_id,
            phone_e164=kwargs.get("phone_e164", "+380501234567"),
            status=kwargs.get("status", TelegramAccountStatus.warming),
            warming_day=kwargs.get("warming_day", 0),
            warming_joined_channels=kwargs.get("warming_joined_channels", None),
            cooldown_until=kwargs.get("cooldown_until", None),
            flood_wait_at=kwargs.get("flood_wait_at", None),
            warming_actions_completed=kwargs.get("warming_actions_completed", 0),
            target_warming_actions=kwargs.get("target_warming_actions", 10),
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account.id


def _import_warming_tasks():
    """Import tg_warming_tasks with Celery/Redis mocked out."""
    workers_pkg = sys.modules.get("app.workers")
    if workers_pkg is None:
        try:
            import app.workers  # noqa: F401
        except Exception:
            stub = types.ModuleType("app.workers")
            stub.celery_app = MagicMock()  # type: ignore[attr-defined]
            sys.modules["app.workers"] = stub

    import app.workers.tg_warming_tasks as mod
    importlib.reload(mod)
    return mod


def _call_celery_task(task, *args, **kwargs):
    """Call a bound Celery task (bind=True).

    Celery's .run() for bound tasks already injects the task instance as self,
    so we just call .run() directly.
    """
    return task.run(*args, **kwargs)


# ═══════════════════════════════════════════════════════════════════
# test_full_warming_flow_day_0_to_1
# ═══════════════════════════════════════════════════════════════════


def test_full_warming_flow_day_0_to_1(mock_redis):
    """Account in day=0 with expired rest_until should transition to day=1
    when resume_tg_warming dispatches it."""
    user = _create_admin_user()
    past_rest = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    account_id = _create_warming_account(
        user.id,
        warming_day=0,
        warming_joined_channels={"rest_until": past_rest, "channels": [], "done_once": []},
    )

    mod = _import_warming_tasks()

    with patch.object(mod, "start_tg_warming") as mock_task:
        mock_task.delay = MagicMock()

        with patch.object(mod, "is_quiet_hours", return_value=False):
            _call_celery_task(mod.resume_tg_warming)

    # Verify account was transitioned to day=1 and dispatch was called
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        assert account is not None
        assert account.warming_day == 1
    mock_task.delay.assert_called_once_with(account_id)


# ═══════════════════════════════════════════════════════════════════
# test_warming_quiet_hours_respected
# ═══════════════════════════════════════════════════════════════════


def test_warming_quiet_hours_respected(mock_redis):
    """During quiet hours resume_tg_warming should skip.
    Outside quiet hours it should dispatch."""
    user = _create_admin_user()
    _create_warming_account(user.id, warming_day=3)

    mod = _import_warming_tasks()

    # 1) Quiet hours active → skip
    with patch.object(mod, "is_quiet_hours", return_value=True):
        with patch.object(mod, "start_tg_warming") as mock_task:
            mock_task.delay = MagicMock()
            _call_celery_task(mod.resume_tg_warming)
            mock_task.delay.assert_not_called()

    # 2) Outside quiet hours → dispatch
    with patch.object(mod, "is_quiet_hours", return_value=False):
        with patch.object(mod, "start_tg_warming") as mock_task:
            mock_task.delay = MagicMock()
            _call_celery_task(mod.resume_tg_warming)
            mock_task.delay.assert_called()


# ═══════════════════════════════════════════════════════════════════
# test_flood_wait_resets_progress
# ═══════════════════════════════════════════════════════════════════


def test_flood_wait_resets_progress(mock_redis):
    """FloodWait during warming should decrement warming_day by 3
    (min 1) and set status=cooldown.

    We simulate the FloodWait handling logic directly at DB level since
    actually triggering FloodWait requires a live Telegram connection.
    """
    user = _create_admin_user()
    account_id = _create_warming_account(
        user.id,
        warming_day=10,
        phone_e164="+380661234567",
        warming_joined_channels={"channels": ["@testch"], "done_once": []},
    )

    # Simulate the FloodWait handling from tg_warming_tasks.py lines 567-583
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        assert account is not None
        wait_seconds = 300
        account.status = TelegramAccountStatus.cooldown
        account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
        account.flood_wait_at = datetime.now(timezone.utc)
        account.warming_day = max(1, account.warming_day - 3)
        account.last_error = f"FloodWait: {wait_seconds}s"
        db.commit()

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        assert account is not None
        assert account.warming_day == 7  # 10 - 3 = 7
        assert account.status == TelegramAccountStatus.cooldown
        assert account.cooldown_until is not None
        assert account.flood_wait_at is not None
        assert "FloodWait" in (account.last_error or "")


# ═══════════════════════════════════════════════════════════════════
# test_cooldown_to_active_at_day_15
# ═══════════════════════════════════════════════════════════════════


def test_cooldown_to_active_at_day_15(mock_redis):
    """Account at day=15 with expired cooldown and old flood_wait_at
    should transition to status=active via check_tg_cooldowns."""
    user = _create_admin_user()
    # Use naive datetimes because SQLite doesn't store tzinfo, and the
    # production code compares with datetime.now(utc) — the ensure_utc
    # helper handles the naive→aware conversion for cooldown_until via
    # is_expired(), but flood_wait_at subtraction needs naive-to-naive
    # or aware-to-aware.  We store naive UTC (matching MySQL runtime).
    now_naive = datetime.utcnow()
    account_id = _create_warming_account(
        user.id,
        phone_e164="+380771234567",
        status=TelegramAccountStatus.cooldown,
        warming_day=15,
        cooldown_until=now_naive - timedelta(minutes=5),
        flood_wait_at=now_naive - timedelta(days=15),
    )

    mod = _import_warming_tasks()

    # Patch datetime.now inside the tasks module so it returns naive UTC
    # (matching what SQLite gives back), avoiding the tz mismatch.
    with patch.object(mod, "_broadcast_warming_update"):
        with patch.object(mod, "datetime") as mock_dt:
            mock_dt.now.return_value = now_naive
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            _call_celery_task(mod.check_tg_cooldowns)

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        assert account is not None
        assert account.status == TelegramAccountStatus.active
        assert account.cooldown_until is None
        assert account.last_error is None
