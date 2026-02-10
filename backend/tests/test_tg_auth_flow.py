"""Tests for the Telegram auth flow: send_code_task, confirm_code_task,
create_tg_account_client, polling endpoint, and the full E2E happy path.

These tests cover the critical path for the OTP auth flow bug fix:
- client creation no longer raises TypeError (duplicate name kwarg)
- task failure properly transitions flow_state to "failed"
- phone numbers are sanitized from error messages
- polling endpoint returns updated state
- ACL is enforced
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.models.user import User


def _create_user(db, telegram_id: int = 9001, is_admin: bool = False) -> User:
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


def _create_account(db, user: User, phone: str = "+380501234567") -> TelegramAccount:
    account = TelegramAccount(
        owner_user_id=user.id,
        phone_e164=phone,
        status=TelegramAccountStatus.new,
        device_config={
            "device_model": "TestDevice",
            "system_version": "Android 14",
            "app_version": "10.14.5",
            "lang_code": "en",
        },
    )
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def _create_flow(
    db,
    account: TelegramAccount,
    state: AuthFlowState = AuthFlowState.init,
) -> TelegramAuthFlow:
    flow = TelegramAuthFlow(
        account_id=account.id,
        phone_e164=account.phone_e164,
        state=state,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=300),
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return flow


# ─── create_tg_account_client: no duplicate kwargs ──────────────────


class TestCreateTgAccountClientKwargs:
    """Verify build_pyrogram_client_kwargs filters out unknown params."""

    def test_device_params_filtered(self):
        from app.clients.telegram_client import build_pyrogram_client_kwargs

        device_config = {
            "device_model": "TestDevice",
            "system_version": "Android 14",
            "app_version": "10.14.5",
            "lang_code": "en",
            "system_lang_code": "en",
            "device_brand": "test",       # Not a Client param
            "app_build_id": "abc123",      # Not a Client param
        }
        result = build_pyrogram_client_kwargs(device_config)
        # device_brand and app_build_id should be filtered out
        assert "device_brand" not in result
        assert "app_build_id" not in result

    def test_empty_config_returns_empty(self):
        from app.clients.telegram_client import build_pyrogram_client_kwargs

        assert build_pyrogram_client_kwargs(None) == {}
        assert build_pyrogram_client_kwargs({}) == {}

    def test_name_not_in_kwargs_after_build(self):
        """The name param must NOT be included in kwargs built from device_config,
        because create_tg_account_client passes name as an explicit argument.
        """
        from app.clients.telegram_client import build_pyrogram_client_kwargs

        # Even if someone sneaked 'name' into device_config it should be filtered
        device_config = {
            "device_model": "TestDevice",
            "name": "should-be-ignored",
        }
        result = build_pyrogram_client_kwargs(device_config)
        assert "name" not in result


# ─── send_code_task: happy path ────────────────────────────────────


class TestSendCodeTaskSuccess:
    def test_send_code_happy_path(self, db_session, monkeypatch):
        user = _create_user(db_session)
        account = _create_account(db_session, user)
        flow = _create_flow(db_session, account)

        mock_client = AsyncMock()
        mock_sent_code = MagicMock()
        mock_sent_code.phone_code_hash = "test_hash_123"
        mock_sent_code.type = "sms"
        mock_client.send_code = AsyncMock(return_value=mock_sent_code)
        mock_client.connect = AsyncMock()
        mock_client.disconnect = AsyncMock()

        monkeypatch.setattr(
            "app.workers.tg_auth_tasks.create_tg_account_client",
            lambda *a, **kw: mock_client,
        )
        monkeypatch.setattr(
            "app.workers.tg_auth_tasks.manager",
            MagicMock(),
        )

        from app.workers.tg_auth_tasks import _run_send_code

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_send_code(account.id, flow.id))
        finally:
            loop.close()

        db_session.expire_all()
        flow = db_session.get(TelegramAuthFlow, flow.id)
        account = db_session.get(TelegramAccount, account.id)

        assert flow.state == AuthFlowState.wait_code
        assert flow.meta_json["phone_code_hash"] == "test_hash_123"
        assert flow.sent_at is not None
        assert account.status == TelegramAccountStatus.code_sent
        assert account.last_error is None


# ─── send_code_task: exception paths ───────────────────────────────


class TestSendCodeTaskFailure:
    def test_client_creation_error_sets_failed(self, db_session, monkeypatch):
        """If create_tg_account_client raises TypeError, flow -> failed."""
        user = _create_user(db_session)
        account = _create_account(db_session, user)
        flow = _create_flow(db_session, account)

        def _raise(*a, **kw):
            raise TypeError(
                "Client.__init__() got multiple values for keyword argument 'name'"
            )

        monkeypatch.setattr(
            "app.workers.tg_auth_tasks.create_tg_account_client", _raise,
        )
        monkeypatch.setattr("app.workers.tg_auth_tasks.manager", MagicMock())

        from app.workers.tg_auth_tasks import _run_send_code

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_send_code(account.id, flow.id))
        finally:
            loop.close()

        db_session.expire_all()
        flow = db_session.get(TelegramAuthFlow, flow.id)
        account = db_session.get(TelegramAccount, account.id)

        assert flow.state == AuthFlowState.failed
        assert flow.last_error is not None
        assert "name" in flow.last_error
        assert account.status == TelegramAccountStatus.error

    def test_telegram_disabled_sets_failed(self, db_session, monkeypatch):
        user = _create_user(db_session)
        account = _create_account(db_session, user)
        flow = _create_flow(db_session, account)

        from app.clients.telegram_client import TelegramClientDisabledError

        def _raise(*a, **kw):
            raise TelegramClientDisabledError()

        monkeypatch.setattr(
            "app.workers.tg_auth_tasks.create_tg_account_client", _raise,
        )
        monkeypatch.setattr("app.workers.tg_auth_tasks.manager", MagicMock())

        from app.workers.tg_auth_tasks import _run_send_code

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_send_code(account.id, flow.id))
        finally:
            loop.close()

        db_session.expire_all()
        flow = db_session.get(TelegramAuthFlow, flow.id)
        account = db_session.get(TelegramAccount, account.id)

        assert flow.state == AuthFlowState.failed
        assert "disabled" in (flow.last_error or "").lower()
        assert account.status == TelegramAccountStatus.error

    def test_error_does_not_leak_phone(self, db_session, monkeypatch):
        user = _create_user(db_session)
        account = _create_account(db_session, user, phone="+380509876543")
        flow = _create_flow(db_session, account)

        def _raise(*a, **kw):
            raise RuntimeError("Failed for +380509876543: network error")

        monkeypatch.setattr(
            "app.workers.tg_auth_tasks.create_tg_account_client", _raise,
        )
        monkeypatch.setattr("app.workers.tg_auth_tasks.manager", MagicMock())

        from app.workers.tg_auth_tasks import _run_send_code

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_send_code(account.id, flow.id))
        finally:
            loop.close()

        db_session.expire_all()
        flow = db_session.get(TelegramAuthFlow, flow.id)
        account = db_session.get(TelegramAccount, account.id)

        assert flow.state == AuthFlowState.failed
        assert "+380509876543" not in (flow.last_error or "")
        assert "+380509876543" not in (account.last_error or "")
        assert "***" in (flow.last_error or "")

    def test_connect_failure_sets_failed(self, db_session, monkeypatch):
        """Network errors during client.connect() also go to failed."""
        user = _create_user(db_session)
        account = _create_account(db_session, user)
        flow = _create_flow(db_session, account)

        mock_client = AsyncMock()
        mock_client.connect = AsyncMock(side_effect=ConnectionError("timeout"))
        mock_client.disconnect = AsyncMock()

        monkeypatch.setattr(
            "app.workers.tg_auth_tasks.create_tg_account_client",
            lambda *a, **kw: mock_client,
        )
        monkeypatch.setattr("app.workers.tg_auth_tasks.manager", MagicMock())

        from app.workers.tg_auth_tasks import _run_send_code

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run_send_code(account.id, flow.id))
        finally:
            loop.close()

        db_session.expire_all()
        flow = db_session.get(TelegramAuthFlow, flow.id)
        assert flow.state == AuthFlowState.failed
        assert "timeout" in (flow.last_error or "").lower()


# ─── send-code endpoint: creates flow + dispatches task ─────────────


class TestSendCodeEndpoint:
    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self, monkeypatch):
        from app.core.rate_limit import limiter
        monkeypatch.setattr(limiter, "enabled", False)

    def test_creates_flow_and_dispatches(self, client, db_session, monkeypatch):
        task_calls: list = []

        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type(
                "FakeTask", (),
                {"delay": staticmethod(lambda *a, **kw: task_calls.append((a, kw)))},
            )(),
        )

        user = _create_user(db_session)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380501234567"},
            headers=headers,
        )
        assert create_resp.status_code == 201
        account_id = create_resp.json()["id"]

        resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "flow_id" in data
        assert len(data["flow_id"]) == 36

        # Verify task was dispatched with correct args
        assert len(task_calls) == 1
        args = task_calls[0][0]
        assert args[0] == account_id
        assert args[1] == data["flow_id"]

        # Verify flow exists in DB with init state
        flow = db_session.get(TelegramAuthFlow, data["flow_id"])
        assert flow is not None
        assert flow.state == AuthFlowState.init
        assert flow.account_id == account_id

    def test_expires_old_flows(self, client, db_session, monkeypatch):
        """Sending a new code should expire any active flows."""
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session, telegram_id=9010)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380509010010"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]

        # First send-code
        resp1 = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id_1 = resp1.json()["flow_id"]

        # Second send-code should expire the first flow
        resp2 = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id_2 = resp2.json()["flow_id"]
        assert flow_id_1 != flow_id_2

        db_session.expire_all()
        old_flow = db_session.get(TelegramAuthFlow, flow_id_1)
        assert old_flow.state == AuthFlowState.expired


# ─── auth-flow polling endpoint ─────────────────────────────────────


class TestAuthFlowPollingEndpoint:
    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self, monkeypatch):
        from app.core.rate_limit import limiter
        monkeypatch.setattr(limiter, "enabled", False)

    def test_poll_returns_updated_state(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session, telegram_id=8001)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380508001001"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        # Simulate worker updating
        flow = db_session.get(TelegramAuthFlow, flow_id)
        flow.state = AuthFlowState.wait_code
        flow.sent_at = datetime.now(timezone.utc)
        account_obj = db_session.get(TelegramAccount, account_id)
        account_obj.status = TelegramAccountStatus.code_sent
        account_obj.last_error = None
        db_session.commit()

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["flow_state"] == "wait_code"
        assert data["account_status"] == "code_sent"

    def test_poll_returns_failed_with_error(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user = _create_user(db_session, telegram_id=8002)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380508002002"},
            headers=headers,
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        flow_id = send_resp.json()["flow_id"]

        # Simulate worker failure
        flow = db_session.get(TelegramAuthFlow, flow_id)
        flow.state = AuthFlowState.failed
        flow.last_error = "Client init error"
        account_obj = db_session.get(TelegramAccount, account_id)
        account_obj.status = TelegramAccountStatus.error
        account_obj.last_error = "Client init error"
        db_session.commit()

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["flow_state"] == "failed"
        assert data["account_status"] == "error"
        assert data["last_error"] == "Client init error"

    def test_poll_acl_denies_other_user(self, client, db_session, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
        )

        user1 = _create_user(db_session, telegram_id=8003)
        user2 = _create_user(db_session, telegram_id=8004)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380508003003"},
            headers=_auth_headers(user1),
        )
        account_id = create_resp.json()["id"]
        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=_auth_headers(user1),
        )
        flow_id = send_resp.json()["flow_id"]

        resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=_auth_headers(user2),
        )
        assert resp.status_code == 404


# ─── E2E: mock Telegram, verify full flow ────────────────────────


class TestE2ESendCode:
    @pytest.fixture(autouse=True)
    def _disable_rate_limit(self, monkeypatch):
        from app.core.rate_limit import limiter
        monkeypatch.setattr(limiter, "enabled", False)

    def test_e2e_send_code_then_poll(self, client, db_session, monkeypatch):
        """E2E: send-code dispatches task, worker updates DB, polling returns wait_code.

        Since we can't run asyncio inside the ASGI test loop, we simulate the
        worker by updating the DB directly in fake_delay (same effect).
        """

        def fake_delay(account_id, flow_id):
            # Simulate what _run_send_code does on success:
            # open a new DB session (like the real worker does)
            with SessionLocal() as wdb:
                flow = wdb.get(TelegramAuthFlow, flow_id)
                account = wdb.get(TelegramAccount, account_id)
                flow.state = AuthFlowState.wait_code
                flow.sent_at = datetime.now(timezone.utc)
                flow.meta_json = {"phone_code_hash": "e2e_hash_456"}
                account.status = TelegramAccountStatus.code_sent
                account.last_error = None
                wdb.commit()

        monkeypatch.setattr(
            "app.api.v1.tg_accounts.send_code_task",
            type("FakeTask", (), {"delay": staticmethod(fake_delay)})(),
        )

        user = _create_user(db_session, telegram_id=8010)
        headers = _auth_headers(user)
        create_resp = client.post(
            "/api/v1/tg-accounts",
            json={"phone": "+380508010010"},
            headers=headers,
        )
        assert create_resp.status_code == 201
        account_id = create_resp.json()["id"]

        send_resp = client.post(
            f"/api/v1/tg-accounts/{account_id}/send-code",
            headers=headers,
        )
        assert send_resp.status_code == 200
        flow_id = send_resp.json()["flow_id"]

        poll_resp = client.get(
            f"/api/v1/tg-accounts/{account_id}/auth-flow/{flow_id}",
            headers=headers,
        )
        assert poll_resp.status_code == 200
        data = poll_resp.json()
        assert data["flow_state"] == "wait_code"
        assert data["account_status"] == "code_sent"
        assert data["last_error"] is None


# ─── Sanitization utilities ────────────────────────────────────────


class TestSanitizationUtils:
    def test_sanitize_error_multiple_phones(self):
        from app.workers.tg_auth_tasks import _sanitize_error

        msg = "Error +380501111111 and +380502222222 both failed"
        result = _sanitize_error(msg)
        assert "+380501111111" not in result
        assert "+380502222222" not in result

    def test_mask_phone_standard(self):
        from app.workers.tg_auth_tasks import _mask_phone

        assert _mask_phone("+380501234567") == "+380*****4567"

    def test_mask_phone_short(self):
        from app.workers.tg_auth_tasks import _mask_phone

        assert _mask_phone("+12345") == "***"

    def test_mask_phone_empty(self):
        from app.workers.tg_auth_tasks import _mask_phone

        assert _mask_phone("") == "***"
