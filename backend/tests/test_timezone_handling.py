"""Regression tests for timezone-aware datetime handling.

MySQL DATETIME columns return naive datetimes via PyMySQL.  The application
must normalise them to UTC-aware before any comparison with
``datetime.now(timezone.utc)``.  These tests verify that:

1. The ``ensure_utc`` helper works correctly.
2. The confirm-code endpoint does NOT crash when ``flow.expires_at`` is naive
   (the exact bug that caused the 500 Internal Server Error).
3. The polling endpoint handles naive ``created_at`` without error.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.core.tz import ensure_utc, utcnow
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.models.user import User


# ─── ensure_utc unit tests ───────────────────────────────────────────


class TestEnsureUtc:
    def test_none_returns_none(self):
        assert ensure_utc(None) is None

    def test_naive_gets_utc(self):
        naive = datetime(2026, 1, 15, 12, 0, 0)
        result = ensure_utc(naive)
        assert result.tzinfo is timezone.utc
        assert result.year == 2026
        assert result.hour == 12

    def test_aware_unchanged(self):
        aware = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        result = ensure_utc(aware)
        assert result is aware

    def test_utcnow_is_aware(self):
        now = utcnow()
        assert now.tzinfo is timezone.utc

    def test_naive_comparable_with_aware_after_ensure(self):
        """The exact scenario that caused the 500 error."""
        naive_from_db = datetime(2026, 2, 10, 14, 30, 0)  # no tzinfo
        now_aware = datetime.now(timezone.utc)

        # Without ensure_utc this raises TypeError
        with pytest.raises(TypeError):
            _ = naive_from_db < now_aware

        # With ensure_utc it works
        result = ensure_utc(naive_from_db) < now_aware
        assert isinstance(result, bool)


# ─── helpers ──────────────────────────────────────────────────────────


def _create_user(db, telegram_id: int = 7001) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"tz_user_{telegram_id}",
        first_name="TzTest",
        is_admin=False,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _create_account(db, user: User, phone: str = "+380507001001") -> TelegramAccount:
    account = TelegramAccount(
        owner_user_id=user.id,
        phone_e164=phone,
        status=TelegramAccountStatus.code_sent,
        device_config={"device_model": "TzTest", "system_version": "Android 14",
                       "app_version": "10.14.5", "lang_code": "en"},
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _create_flow_with_naive_expires(
    db,
    account: TelegramAccount,
    state: AuthFlowState = AuthFlowState.wait_code,
    expired: bool = False,
) -> TelegramAuthFlow:
    """Create a flow and force ``expires_at`` to be a naive datetime.

    This simulates what happens when MySQL returns a DATETIME value without
    timezone info through PyMySQL.
    """
    if expired:
        naive_expires = datetime(2020, 1, 1, 0, 0, 0)  # way in the past, naive
    else:
        naive_expires = datetime.utcnow() + timedelta(seconds=300)  # future, naive

    flow = TelegramAuthFlow(
        account_id=account.id,
        phone_e164=account.phone_e164,
        state=state,
        expires_at=naive_expires,
        meta_json={"phone_code_hash": "test_hash"},
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)

    # Force expires_at to be naive (simulating MySQL read-back).
    # SQLite may or may not preserve tzinfo depending on driver, so we
    # explicitly strip it to guarantee the test exercises the fix.
    flow.expires_at = naive_expires
    db.commit()
    db.refresh(flow)
    return flow


# ─── confirm-code regression test ───────────────────────────────────


class TestConfirmCodeTimezoneRegression:
    """Regression: POST /confirm-code must not crash with naive expires_at."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self, monkeypatch):
        from app.core.rate_limit import limiter
        monkeypatch.setattr(limiter, "enabled", False)

    def test_confirm_code_with_naive_expires_not_expired(
        self, client, db_session, monkeypatch,
    ):
        """A flow with naive expires_at (future) should dispatch the task
        instead of crashing with TypeError."""
        # Stub out confirm_code_task so it doesn't hit real Celery/Redis
        calls = []

        class FakeTask:
            name = "confirm_code_task"
            def delay(self, *a, **kw):
                calls.append((a, kw))

        monkeypatch.setattr("app.api.v1.tg_accounts.confirm_code_task", FakeTask())

        user = _create_user(db_session, telegram_id=7010)
        headers = _auth_headers(user)
        account = _create_account(db_session, user, phone="+380507010010")
        flow = _create_flow_with_naive_expires(
            db_session, account, state=AuthFlowState.wait_code, expired=False,
        )

        resp = client.post(
            f"/api/v1/tg-accounts/{account.id}/confirm-code",
            json={"flow_id": flow.id, "code": "12345"},
            headers=headers,
        )

        # Must NOT be 500.  Should be 200 (task dispatched).
        assert resp.status_code == 200, f"Expected 200 but got {resp.status_code}: {resp.text}"
        assert len(calls) == 1

    def test_confirm_code_with_naive_expires_expired(
        self, client, db_session, monkeypatch,
    ):
        """A flow with naive expires_at (past) should return 409, not 500."""
        class FakeTask:
            name = "confirm_code_task"
            def delay(self, *a, **kw):
                pass

        monkeypatch.setattr("app.api.v1.tg_accounts.confirm_code_task", FakeTask())

        user = _create_user(db_session, telegram_id=7011)
        headers = _auth_headers(user)
        account = _create_account(db_session, user, phone="+380507011011")
        flow = _create_flow_with_naive_expires(
            db_session, account, state=AuthFlowState.wait_code, expired=True,
        )

        resp = client.post(
            f"/api/v1/tg-accounts/{account.id}/confirm-code",
            json={"flow_id": flow.id, "code": "12345"},
            headers=headers,
        )

        # Must be 409 (expired), NOT 500
        assert resp.status_code == 409, f"Expected 409 but got {resp.status_code}: {resp.text}"


# ─── polling endpoint regression test ──────────────────────────────


class TestPollingTimezoneRegression:
    """Regression: GET /auth-flow/{flow_id} must handle naive created_at."""

    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self, monkeypatch):
        from app.core.rate_limit import limiter
        monkeypatch.setattr(limiter, "enabled", False)

    def test_poll_stale_init_flow_with_naive_created_at(
        self, client, db_session, monkeypatch,
    ):
        """A flow stuck in 'init' with a naive created_at (>60s old) should
        auto-fail without crashing."""
        user = _create_user(db_session, telegram_id=7020)
        headers = _auth_headers(user)
        account = _create_account(db_session, user, phone="+380507020020")

        # Create flow, then force created_at to be naive and old
        flow = TelegramAuthFlow(
            account_id=account.id,
            phone_e164=account.phone_e164,
            state=AuthFlowState.init,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
        )
        db_session.add(flow)
        db_session.commit()
        db_session.refresh(flow)

        # Force naive created_at 120 seconds ago (simulating MySQL)
        naive_old = datetime.utcnow() - timedelta(seconds=120)
        flow.created_at = naive_old
        db_session.commit()
        db_session.refresh(flow)

        resp = client.get(
            f"/api/v1/tg-accounts/{account.id}/auth-flow/{flow.id}",
            headers=headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["flow_state"] == "failed"
        assert "timeout" in data["last_error"].lower()
