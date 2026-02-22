"""Celery task for Telegram 2FA password confirmation.

Extracted from tg_auth_tasks.py — handles the check_password step
when a Telegram account has two-factor authentication enabled.
"""

import asyncio
import logging
import time
from datetime import datetime, timezone

from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import (
    AuthKeyUnregistered,
    BadRequest,
    FloodWait,
    PhoneNumberBanned,
    SessionRevoked,
)

from app.clients.telegram_client import create_tg_account_client
from app.core.database import SessionLocal
from app.core.metrics import verify_fail_total
from app.core.settings import get_settings
from app.core.tz import is_expired
from app.models.proxy import Proxy
from app.models.telegram_account import (
    TelegramAccount,
    TelegramAccountStatus,
    VerifyReasonCode,
)
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.services.session_crypto import encrypt_session
from app.workers import celery_app
from app.workers.tg_auth_helpers import (
    _broadcast_account_update,
    _broadcast_flow_update,
    _handle_floodwait,
    _is_network_error,
    _mark_proxy_unhealthy,
    _mask_phone,
    _sanitize_error,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── confirm_password (2FA) ─────────────────────────────────────────

async def _run_confirm_password(account_id: int, flow_id: str, password: str) -> None:
    t0 = time.monotonic()
    log = logger.getChild("confirm_password")
    ctx = {"account_id": account_id, "flow_id": flow_id}

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            log.warning("event=confirm_password_not_found %s", ctx)
            return

        masked = _mask_phone(account.phone_e164)
        ctx["phone"] = masked

        if flow.state != AuthFlowState.wait_password:
            flow.last_error = f"Invalid flow state for password: {flow.state}"
            db.commit()
            log.warning("event=confirm_password_bad_state state=%s %s", flow.state, ctx)
            return

        if is_expired(flow.expires_at):
            flow.state = AuthFlowState.expired
            flow.last_error = "Flow expired"
            account.status = TelegramAccountStatus.error
            account.last_error = "Verification flow expired"
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        flow.attempts += 1
        if flow.attempts > settings.auth_flow_max_attempts:
            flow.state = AuthFlowState.failed
            flow.last_error = "Too many attempts"
            account.status = TelegramAccountStatus.error
            account.last_error = "Too many password attempts"
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        if not account.session_encrypted:
            log.error("event=confirm_password_no_session %s", ctx)
            flow.state = AuthFlowState.failed
            flow.last_error = "No session saved from auth step. Please restart auth flow."
            account.status = TelegramAccountStatus.error
            account.last_error = "No session for 2FA. Please resend code."
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None

        client = None
        try:
            log.info("event=confirm_password_started %s", ctx)
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)

            t_connect = time.monotonic()
            await asyncio.wait_for(client.connect(), timeout=30)
            log.info(
                "event=client_connected %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_connect) * 1000),
            )

            t_check = time.monotonic()
            await asyncio.wait_for(client.check_password(password), timeout=30)
            log.info(
                "event=check_password_ok %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_check) * 1000),
            )

            session_string = await asyncio.wait_for(client.export_session_string(), timeout=15)
            account.session_encrypted = encrypt_session(session_string)

            me = await asyncio.wait_for(client.get_me(), timeout=15)
            account.tg_user_id = me.id
            account.tg_username = me.username
            account.first_name = me.first_name
            account.last_name = getattr(me, "last_name", None)
            account.status = TelegramAccountStatus.verified
            account.verified_at = datetime.now(timezone.utc)
            account.last_seen_at = datetime.now(timezone.utc)
            account.last_error = None

            flow.state = AuthFlowState.done
            flow.last_error = None
            db.commit()

            elapsed = int((time.monotonic() - t0) * 1000)
            log.info("event=confirm_password_ok %s elapsed_ms=%d", ctx, elapsed)

            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

            # Auto-trigger account sync after successful 2FA verification
            try:
                from app.workers.tg_sync_tasks import sync_account_data
                sync_account_data.delay(account_id)
                log.info("event=sync_dispatched_after_2fa account_id=%d", account_id)
            except Exception as sync_exc:
                log.warning("event=sync_dispatch_failed account_id=%d error=%s", account_id, sync_exc)

        except BadRequest as exc:
            if "PASSWORD_HASH_INVALID" in str(exc):
                flow.last_error = "Invalid 2FA password"
                account.last_error = "Invalid 2FA password"
            else:
                err = _sanitize_error(str(exc)[:500])
                flow.last_error = err
                account.last_error = err
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.unknown.value).inc()
            log.warning("event=confirm_password_failed reason=bad_request %s", ctx)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except FloodWait as exc:
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            _handle_floodwait(account, exc, db)
            verify_fail_total.labels(reason=VerifyReasonCode.floodwait.value).inc()
            log.warning(
                "event=confirm_password_failed reason=flood_wait wait_s=%s %s",
                exc.value, ctx,
            )
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneNumberBanned:
            flow.state = AuthFlowState.failed
            flow.last_error = "Phone number is banned by Telegram"
            account.status = TelegramAccountStatus.banned
            account.last_error = "Phone number is banned by Telegram"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_banned.value).inc()
            log.warning("event=confirm_password_failed reason=phone_banned %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except (SessionRevoked, AuthKeyUnregistered):
            flow.state = AuthFlowState.failed
            flow.last_error = "Session revoked or auth key unregistered"
            account.status = TelegramAccountStatus.error
            account.session_encrypted = None
            account.last_error = "Session revoked or auth key unregistered"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.session_revoked.value).inc()
            log.warning("event=confirm_password_failed reason=session_revoked %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            elapsed = int((time.monotonic() - t0) * 1000)

            reason = VerifyReasonCode.network if _is_network_error(exc) else VerifyReasonCode.unknown
            if reason == VerifyReasonCode.network and proxy:
                _mark_proxy_unhealthy(proxy, db)

            log.exception(
                "event=confirm_password_failed reason=%s %s error=%s elapsed_ms=%d",
                reason.value, ctx, err_msg, elapsed,
            )
            flow.state = AuthFlowState.failed
            flow.last_error = err_msg
            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            db.commit()
            verify_fail_total.labels(reason=reason.value).inc()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=10)
                except Exception:
                    pass


@celery_app.task(
    name="app.workers.tg_auth_tasks.confirm_password_task",
    bind=True,
    soft_time_limit=300,
    time_limit=360,
)
def confirm_password_task(self, account_id: int, flow_id: str, password: str) -> None:
    logger.info(
        "event=confirm_password_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    try:
        asyncio.run(_run_confirm_password(account_id, flow_id, password))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s, flow_id=%s)", self.request.id, account_id, flow_id)
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            flow = db.get(TelegramAuthFlow, flow_id)
            if account:
                account.status = TelegramAccountStatus.error
                account.last_error = "Task timed out"
            if flow:
                flow.state = AuthFlowState.failed
                flow.last_error = "Task timed out"
            db.commit()
        return
    logger.info(
        "event=confirm_password_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )
