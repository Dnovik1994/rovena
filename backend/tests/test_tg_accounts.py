"""Tests for the Telegram account OTP auth flow (tg-accounts endpoints)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.models.user import User


def _create_user(db, telegram_id: int = 1001, is_admin: bool = False) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"user_{telegram_id}",
        first_name="Test",
        is_admin=is_admin,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_headers(user: User) -> dict[str, str]:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ─── POST /tg-accounts (create) ─────────────────────────────────────


class TestCreateTgAccount:
    def test_create_account_success(self, client, db_session):
        user = _create_user(db_session)
        resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["phone_e164"] == "+380501234567"
        assert data["status"] == "new"
        assert data["owner_user_id"] == user.id
        assert data["device_config"] is not None

    def test_create_account_idempotent(self, client, db_session):
        user = _create_user(db_session)
        headers = _auth_headers(user)
        resp1 = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        resp2 = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        assert resp1.json()["id"] == resp2.json()["id"]

    def test_create_account_invalid_phone(self, client, db_session):
        user = _create_user(db_session)
        resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "not-a-phone"},
            headers=_auth_headers(user),
        )
        assert resp.status_code == 422

    def test_create_account_no_auth(self, client):
        resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
        )
        assert resp.status_code == 401


# ─── GET /tg-accounts (list) ────────────────────────────────────────


class TestListTgAccounts:
    def test_list_accounts_empty(self, client, db_session):
        user = _create_user(db_session)
        resp = client.get(
            "/api/v1/tg-accounts",
            headers=_auth_headers(user),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_accounts_returns_own(self, client, db_session):
        user = _create_user(db_session)
        headers = _auth_headers(user)
        client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501111111"},
            headers=headers,
        )
        resp = client.get("/api/v1/tg-accounts", headers=headers)
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_accounts_isolated_by_owner(self, client, db_session):
        user1 = _create_user(db_session, telegram_id=2001)
        user2 = _create_user(db_session, telegram_id=2002)
        client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501111111"},
            headers=_auth_headers(user1),
        )
        resp = client.get(
            "/api/v1/tg-accounts",
            headers=_auth_headers(user2),
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 0

    def test_admin_sees_all(self, client, db_session):
        user1 = _create_user(db_session, telegram_id=3001)
        admin = _create_user(db_session, telegram_id=3002, is_admin=True)
        client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501111111"},
            headers=_auth_headers(user1),
        )
        resp = client.get(
            "/api/v1/tg-accounts",
            headers=_auth_headers(admin),
        )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1


# ─── GET /tg-accounts/{id} ──────────────────────────────────────────


class TestGetTgAccount:
    def test_get_own_account(self, client, db_session):
        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        resp = client.get(f"/api/v1/tg-accounts/{account_id}", headers=headers)
        assert resp.status_code == 200
        assert resp.json()["id"] == account_id

    def test_get_other_user_account_404(self, client, db_session):
        user1 = _create_user(db_session, telegram_id=4001)
        user2 = _create_user(db_session, telegram_id=4002)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=_auth_headers(user1),
        )
        account_id = create_resp.json()["id"]
        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}",
            headers=_auth_headers(user2),
        )
        assert resp.status_code == 404


# ─── State machine tests ────────────────────────────────────────────


class TestStateMachine:
    def test_send_code_from_new_state(self, client, db_session, monkeypatch):
        # Mock the celery task to avoid actual execution
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "flow_id" in data
        assert len(data["flow_id"]) == 36  # UUID format

    def test_send_code_not_allowed_from_verified(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        # Manually set status to verified
        db = SessionLocal()
        account = db.get(TelegramAccount, account_id)
        account.status = TelegramAccountStatus.verified
        db.commit()
        db.close()

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        assert resp.status_code == 409

    def test_confirm_code_without_flow_404(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.confirm_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/confirm-code",
            json={"flow_id": "nonexistent-flow-id-00000000000", "code": "12345"},
            headers=headers,
        )
        assert resp.status_code == 404

    def test_confirm_password_wrong_state(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.confirm_password_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        # Create a flow in wait_code state (not wait_password)
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/confirm-password",
            json={"flow_id": flow_id, "password": "test123"},
            headers=headers,
        )
        # Flow is in init state (worker hasn't processed it yet), not wait_password
        assert resp.status_code == 409


# ─── Disconnect ──────────────────────────────────────────────────────


class TestDisconnect:
    def test_disconnect_verified_account(self, client, db_session):
        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        # Set to verified
        db = SessionLocal()
        account = db.get(TelegramAccount, account_id)
        account.status = TelegramAccountStatus.verified
        account.session_encrypted = "fake-encrypted-session"
        db.commit()
        db.close()

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/disconnect",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "disconnected"


# ─── Regenerate device ───────────────────────────────────────────────


class TestRegenerateDevice:
    def test_regenerate_device(self, client, db_session):
        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        old_config = create_resp.json()["device_config"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/regenerate-device",
            headers=headers,
        )
        assert resp.status_code == 200
        # Device config should be regenerated (might be same randomly but structure present)
        assert resp.json()["device_config"] is not None
        assert resp.json()["last_device_regenerated_at"] is not None


# ─── Warmup state guard ─────────────────────────────────────────────


class TestWarmupGuard:
    def test_warmup_rejected_for_new_account(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.start_warming",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/warmup",
            headers=headers,
        )
        assert resp.status_code == 409

    def test_warmup_allowed_for_verified(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.start_warming",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        db = SessionLocal()
        account = db.get(TelegramAccount, account_id)
        account.status = TelegramAccountStatus.verified
        db.commit()
        db.close()

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/warmup",
            headers=headers,
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "warming"


# ─── Health check state guard ────────────────────────────────────────


class TestHealthCheckGuard:
    def test_health_check_rejected_for_new(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.account_health_check",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/health-check",
            headers=headers,
        )
        assert resp.status_code == 409


# ─── WebSocket HTTP fallback ────────────────────────────────────────


class TestWsHttpFallback:
    def test_ws_status_http_get_returns_426(self, client):
        resp = client.get("/ws/status")
        assert resp.status_code == 426


# ─── Celery task registration ───────────────────────────────────────


class TestCeleryTaskRegistration:
    def test_auth_tasks_registered(self):
        from app.workers import celery_app
        task_names = list(celery_app.tasks.keys())
        assert any("send_code_task" in name for name in task_names)
        assert any("confirm_code_task" in name for name in task_names)
        assert any("confirm_password_task" in name for name in task_names)


# ─── Auth flow polling endpoint ───────────────────────────────────


class TestAuthFlowPolling:
    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self, monkeypatch):
        """Disable rate limiting so multiple send-code calls don't hit 429."""
        from app.core.rate_limit import limiter
        monkeypatch.setattr(limiter, "enabled", False)

    def test_poll_init_state(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )
        user = _create_user(db_session, telegram_id=5001)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380505001001"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["flow_id"] == flow_id
        assert data["flow_state"] == "init"
        assert data["account_status"] == "new"

    def test_poll_wait_code_state(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )
        user = _create_user(db_session, telegram_id=5002)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380505002002"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        # Use the db_session (same session the client test uses) to update state
        flow = db_session.get(TelegramAuthFlow, flow_id)
        flow.state = AuthFlowState.wait_code
        flow.sent_at = datetime.now(timezone.utc)
        account_obj = db_session.get(TelegramAccount, account_id)
        account_obj.status = TelegramAccountStatus.code_sent
        db_session.commit()

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["flow_state"] == "wait_code"
        assert data["account_status"] == "code_sent"
        assert data["sent_at"] is not None

    def test_poll_failed_state(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )
        user = _create_user(db_session, telegram_id=5003)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380505003003"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        # Update flow to failed state
        flow = db_session.get(TelegramAuthFlow, flow_id)
        flow.state = AuthFlowState.failed
        flow.last_error = "FloodWait: retry after 300s"
        account_obj = db_session.get(TelegramAccount, account_id)
        account_obj.last_error = "FloodWait: 300s"
        db_session.commit()

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["flow_state"] == "failed"
        assert "FloodWait" in data["last_error"]

    def test_poll_nonexistent_flow_404(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )
        user = _create_user(db_session, telegram_id=5004)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380505004004"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/nonexistent-id",
            headers=headers,
        )
        assert resp.status_code == 404

    def test_poll_other_user_account_404(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )
        user = _create_user(db_session, telegram_id=5005)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380505005005"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        other_user = _create_user(db_session, telegram_id=5006)
        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=_auth_headers(other_user),
        )
        assert resp.status_code == 404


# ─── Phone masking utility ──────────────────────────────────────────


class TestPhoneMasking:
    def test_mask_phone_standard(self):
        from app.workers.tg_auth_tasks import _mask_phone
        assert _mask_phone("+380501234567") == "+380*****4567"

    def test_mask_phone_short(self):
        from app.workers.tg_auth_tasks import _mask_phone
        assert _mask_phone("+12345") == "***"

    def test_mask_phone_empty(self):
        from app.workers.tg_auth_tasks import _mask_phone
        assert _mask_phone("") == "***"

    def test_sanitize_error_removes_phone(self):
        from app.workers.tg_auth_tasks import _sanitize_error
        msg = "Error for +380501234567: something failed"
        result = _sanitize_error(msg)
        assert "+380501234567" not in result
        assert "***" in result


# ─── WebSocket routing test ────────────────────────────────────────


class TestWsRouting:
    def test_ws_status_not_index_html(self, client):
        """GET /ws/status must NOT return index.html (SPA fallback).
        It should return 426 Upgrade Required from the backend."""
        resp = client.get("/ws/status")
        assert resp.status_code == 426
        data = resp.json()
        assert data["error"]["code"] == "426"
        assert "WebSocket" in data["error"]["message"]

    def test_ws_upgrade_accepted(self, client, db_session):
        """WebSocket connection to /ws/status should be accepted with valid token."""
        user = _create_user(db_session, telegram_id=7001)
        token = create_access_token(str(user.id))
        with client.websocket_connect(f"/ws/status?token={token}") as websocket:
            # Should get a ping within 30s, but we just verify connection works
            data = websocket.receive_json()
            assert data["type"] == "ping"
