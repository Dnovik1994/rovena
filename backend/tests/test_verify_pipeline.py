"""Tests for the verify pipeline stabilization:

- Lease/lock idempotency (double-launch prevention)
- Status transitions (VerifyStatus enum)
- FloodWait -> cooldown transition
- Proxy unhealthy marking on network errors
- Metrics emission
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.core.database import SessionLocal
from app.models.proxy import Proxy, ProxyStatus, ProxyType
from app.models.telegram_account import (
    VERIFY_LEASE_TTL_SECONDS,
    TelegramAccount,
    TelegramAccountStatus,
    VerifyReasonCode,
    VerifyStatus,
)
from app.models.user import User


# ─── Helpers ──────────────────────────────────────────────────────────

def _create_user(db) -> User:
    user = User(telegram_id=42, username="testuser")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_account(db, user, **kwargs) -> TelegramAccount:
    defaults = dict(
        owner_user_id=user.id,
        phone_e164="+380501234567",
        status=TelegramAccountStatus.verified,
        session_encrypted="encrypted-session-data",
    )
    defaults.update(kwargs)
    account = TelegramAccount(**defaults)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _create_proxy(db) -> Proxy:
    proxy = Proxy(
        host="127.0.0.1",
        port=1080,
        type=ProxyType.socks5,
        status=ProxyStatus.active,
    )
    db.add(proxy)
    db.commit()
    db.refresh(proxy)
    return proxy


# ─── Lease / Lock Tests ──────────────────────────────────────────────

class TestVerifyLease:
    """Test lease acquisition and idempotency."""

    def test_acquire_lease_success(self):
        """First acquire should succeed."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            assert account.verifying is False
            acquired = account.acquire_verify_lease("task-1", db)
            assert acquired is True
            assert account.verifying is True
            assert account.verifying_task_id == "task-1"
            assert account.verify_status == VerifyStatus.running.value
            db.commit()

    def test_acquire_lease_rejected_while_active(self):
        """Second acquire should be rejected while lease is active."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            # First acquire
            assert account.acquire_verify_lease("task-1", db) is True

            # Second acquire should fail
            assert account.acquire_verify_lease("task-2", db) is False
            # Original task_id is still the owner
            assert account.verifying_task_id == "task-1"

    def test_acquire_lease_after_expiry(self):
        """Lease should be acquirable after TTL expires."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            # First acquire
            assert account.acquire_verify_lease("task-1", db) is True
            # Simulate an old start time (expired)
            account.verifying_started_at = datetime.now(timezone.utc) - timedelta(
                seconds=VERIFY_LEASE_TTL_SECONDS + 60,
            )
            db.commit()

            # Now another acquire should succeed (lease expired)
            db.refresh(account)
            assert account.acquire_verify_lease("task-2", db) is True
            assert account.verifying_task_id == "task-2"

    def test_release_lease_ok(self):
        """Release sets verifying=False and records status."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            account.acquire_verify_lease("task-1", db)

            account.release_verify_lease(VerifyStatus.ok)
            db.commit()

            db.refresh(account)
            assert account.verifying is False
            assert account.verifying_started_at is None
            assert account.verifying_task_id is None
            assert account.verify_status == VerifyStatus.ok.value
            assert account.verify_reason is None

    def test_release_lease_failed_with_reason(self):
        """Release with failure records reason code."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            account.acquire_verify_lease("task-1", db)

            account.release_verify_lease(VerifyStatus.failed, VerifyReasonCode.floodwait)
            db.commit()

            db.refresh(account)
            assert account.verify_status == VerifyStatus.failed.value
            assert account.verify_reason == VerifyReasonCode.floodwait.value


# ─── Status Transition Tests ─────────────────────────────────────────

class TestStatusTransitions:
    """Test that VerifyStatus enum covers all required states."""

    def test_all_verify_statuses_exist(self):
        expected = {"pending", "running", "needs_password", "ok", "failed", "cooldown"}
        actual = {s.value for s in VerifyStatus}
        assert expected == actual

    def test_all_reason_codes_exist(self):
        expected = {
            "floodwait", "bad_proxy", "invalid_code", "password_required",
            "network", "client_disabled", "phone_invalid", "code_expired",
            "phone_banned", "session_revoked", "unknown",
        }
        actual = {r.value for r in VerifyReasonCode}
        assert expected == actual

    def test_lease_sets_running_status(self):
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)
            account.acquire_verify_lease("task-1", db)
            assert account.verify_status == VerifyStatus.running.value

    def test_release_cooldown_status(self):
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)
            account.acquire_verify_lease("task-1", db)
            account.release_verify_lease(VerifyStatus.cooldown, VerifyReasonCode.floodwait)
            assert account.verify_status == VerifyStatus.cooldown.value
            assert account.verify_reason == VerifyReasonCode.floodwait.value

    def test_release_needs_password_status(self):
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)
            account.acquire_verify_lease("task-1", db)
            account.release_verify_lease(VerifyStatus.needs_password, VerifyReasonCode.password_required)
            assert account.verify_status == VerifyStatus.needs_password.value


# ─── FloodWait -> Cooldown Tests ─────────────────────────────────────

class TestFloodWaitCooldown:
    """Test that FloodWait errors transition account to cooldown."""

    def test_handle_floodwait_sets_cooldown(self):
        """_handle_floodwait should set cooldown status and until timestamp."""
        from app.workers.tg_auth_tasks import _handle_floodwait

        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            # Create a mock FloodWait exception
            mock_exc = MagicMock()
            mock_exc.value = 120  # 120 seconds

            _handle_floodwait(account, mock_exc, db)

            db.refresh(account)
            assert account.status == TelegramAccountStatus.cooldown
            assert account.cooldown_until is not None
            assert "FloodWait: 120s" in account.last_error

    def test_handle_floodwait_sets_correct_duration(self):
        """cooldown_until should be approximately now + wait_s."""
        from app.workers.tg_auth_tasks import _handle_floodwait

        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)

            mock_exc = MagicMock()
            mock_exc.value = 300

            before = datetime.now(timezone.utc)
            _handle_floodwait(account, mock_exc, db)
            after = datetime.now(timezone.utc)

            db.refresh(account)
            from app.core.tz import ensure_utc
            cooldown = ensure_utc(account.cooldown_until)
            # cooldown_until should be between before+300s and after+300s
            assert cooldown >= before + timedelta(seconds=299)
            assert cooldown <= after + timedelta(seconds=301)


# ─── Proxy Unhealthy Tests ───────────────────────────────────────────

class TestProxyUnhealthy:
    """Test that network errors mark proxy as unhealthy."""

    def test_mark_proxy_unhealthy(self):
        from app.workers.tg_auth_tasks import _mark_proxy_unhealthy

        with SessionLocal() as db:
            proxy = _create_proxy(db)
            assert proxy.status == ProxyStatus.active

            _mark_proxy_unhealthy(proxy, db)

            db.refresh(proxy)
            assert proxy.status == ProxyStatus.error

    def test_mark_proxy_unhealthy_none_proxy(self):
        """Should not raise when proxy is None."""
        from app.workers.tg_auth_tasks import _mark_proxy_unhealthy

        with SessionLocal() as db:
            _mark_proxy_unhealthy(None, db)  # Should not raise


# ─── Network Error Detection Tests ───────────────────────────────────

class TestNetworkErrorDetection:
    def test_timeout_detected(self):
        from app.workers.tg_auth_tasks import _is_network_error
        assert _is_network_error(ConnectionError("Connection timeout")) is True

    def test_connection_refused(self):
        from app.workers.tg_auth_tasks import _is_network_error
        assert _is_network_error(OSError("Connection refused")) is True

    def test_non_network_error(self):
        from app.workers.tg_auth_tasks import _is_network_error
        assert _is_network_error(ValueError("Invalid value")) is False

    def test_eof_error(self):
        from app.workers.tg_auth_tasks import _is_network_error
        assert _is_network_error(EOFError("Unexpected EOF")) is True


# ─── Verify Endpoint Idempotency Tests ───────────────────────────────

class TestVerifyEndpointIdempotency:
    """Test the tg-accounts verify endpoint lease checking."""

    def test_verify_endpoint_returns_already_running(self, monkeypatch, client):
        """When a verify lease is active, endpoint should return running status."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)
            account.verifying = True
            account.verifying_started_at = datetime.now(timezone.utc)
            account.verifying_task_id = "existing-task"
            account.verify_status = VerifyStatus.running.value
            db.commit()
            account_id = account.id
            user_id = user.id

        from app.core.security import create_access_token
        token = create_access_token(str(user_id))

        # Ensure we don't actually dispatch
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.verify_account_task",
            type("FakeTask", (), {
                "name": "verify_account_task",
                "delay": lambda self, *args: None,
            })(),
        )

        response = client.post(
            f"/api/v1/tg-accounts/{account_id}/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verifying"] is True
        assert data["verify_status"] == "running"
        assert "already in progress" in data["message"]

    def test_verify_endpoint_dispatches_new_task(self, monkeypatch, client):
        """When no lease is active, endpoint should dispatch a new task."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user)
            account_id = account.id
            user_id = user.id

        from app.core.security import create_access_token
        token = create_access_token(str(user_id))

        dispatched = []
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.verify_account_task",
            type("FakeTask", (), {
                "name": "verify_account_task",
                "delay": lambda self, *args: dispatched.append(args),
            })(),
        )

        response = client.post(
            f"/api/v1/tg-accounts/{account_id}/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["verify_status"] == "pending"
        assert len(dispatched) == 1

    def test_verify_endpoint_rejects_wrong_status(self, monkeypatch, client):
        """Cannot verify an account in 'new' status."""
        with SessionLocal() as db:
            user = _create_user(db)
            account = _create_account(db, user, status=TelegramAccountStatus.new)
            account_id = account.id
            user_id = user.id

        from app.core.security import create_access_token
        token = create_access_token(str(user_id))

        response = client.post(
            f"/api/v1/tg-accounts/{account_id}/verify",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409
