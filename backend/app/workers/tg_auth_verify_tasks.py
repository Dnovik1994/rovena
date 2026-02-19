"""Celery task for verifying existing Telegram account sessions.

Extracted from tg_auth_tasks.py — standalone health-check with
lease-based idempotency.  No auth-flow (OTP) logic lives here.
"""

import asyncio
import logging
import time
import uuid

from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import (
    AuthKeyUnregistered,
    FloodWait,
    PhoneNumberBanned,
    SessionPasswordNeeded,
    SessionRevoked,
)

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.core.metrics import (
    active_verifications,
    verify_account_duration_seconds,
    verify_fail_total,
    verify_lease_acquired_total,
    verify_lease_rejected_total,
)
from app.core.tz import utcnow
from app.models.proxy import Proxy
from app.models.telegram_account import (
    TelegramAccount,
    TelegramAccountStatus,
    VerifyReasonCode,
    VerifyStatus,
)
from app.workers import celery_app
from app.workers.tg_auth_helpers import (
    _broadcast_account_update,
    _handle_floodwait,
    _is_network_error,
    _mark_proxy_unhealthy,
    _sanitize_error,
)

logger = logging.getLogger(__name__)


# ─── verify_account (session health check with lease) ───────────────

async def _run_verify_account(account_id: int, task_id: str) -> None:
    """Verify an existing TelegramAccount session is still valid.

    Uses a DB-level lease (verifying/verifying_started_at/verifying_task_id)
    to guarantee at most one concurrent verification per account.
    """
    t0 = time.monotonic()
    log = logger.getChild("verify_account")
    ctx = {"account_id": account_id, "task_id": task_id}

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        if not account:
            log.warning("event=verify_account_not_found %s", ctx)
            return

        ctx["user_id"] = account.owner_user_id
        ctx["proxy_id"] = account.proxy_id

        # ── Acquire lease (atomic DB-level UPDATE) ──
        if not account.acquire_verify_lease(task_id, db):
            verify_lease_rejected_total.inc()
            log.info(
                "event=verify_account_lease_rejected existing_task_id=%s %s",
                account.verifying_task_id, ctx,
            )
            return
        verify_lease_acquired_total.inc()
        active_verifications.inc()
        log.info("event=verify_account_lease_acquired %s", ctx)

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        client = None

        try:
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)

            t_connect = time.monotonic()
            await asyncio.wait_for(client.connect(), timeout=30)
            log.info(
                "event=verify_client_connected %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_connect) * 1000),
            )

            t_get_me = time.monotonic()
            me = await asyncio.wait_for(client.get_me(), timeout=15)
            log.info(
                "event=verify_get_me_ok %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_get_me) * 1000),
            )

            # Success
            account.tg_user_id = me.id
            account.tg_username = getattr(me, "username", None)
            account.first_name = getattr(me, "first_name", None)
            account.last_name = getattr(me, "last_name", None)
            account.status = TelegramAccountStatus.verified
            account.verified_at = utcnow()
            account.last_seen_at = utcnow()
            account.last_error = None
            account.release_verify_lease(VerifyStatus.ok)
            db.commit()

            elapsed = time.monotonic() - t0
            verify_account_duration_seconds.observe(elapsed)
            log.info(
                "event=verify_account_ok %s result=ok elapsed_ms=%d",
                ctx, int(elapsed * 1000),
            )
            _broadcast_account_update(account)

        except TelegramClientDisabledError:
            account.status = TelegramAccountStatus.error
            account.last_error = "Telegram client disabled"
            account.release_verify_lease(VerifyStatus.failed, VerifyReasonCode.client_disabled)
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.client_disabled.value).inc()
            log.warning("event=verify_account_failed reason=client_disabled %s", ctx)
            _broadcast_account_update(account)

        except SessionPasswordNeeded:
            account.status = TelegramAccountStatus.password_required
            account.last_error = None
            account.release_verify_lease(VerifyStatus.needs_password, VerifyReasonCode.password_required)
            db.commit()

            elapsed = time.monotonic() - t0
            verify_account_duration_seconds.observe(elapsed)
            log.info(
                "event=verify_account_done %s result=needs_password elapsed_ms=%d",
                ctx, int(elapsed * 1000),
            )
            _broadcast_account_update(account)

        except FloodWait as exc:
            wait_s = int(exc.value)
            _handle_floodwait(account, exc, db)
            account.release_verify_lease(VerifyStatus.cooldown, VerifyReasonCode.floodwait)
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.floodwait.value).inc()
            log.warning(
                "event=verify_account_failed reason=floodwait wait_s=%d %s",
                wait_s, ctx,
            )
            _broadcast_account_update(account)

        except PhoneNumberBanned:
            account.status = TelegramAccountStatus.banned
            account.last_error = "Phone number is banned by Telegram"
            account.release_verify_lease(VerifyStatus.failed, VerifyReasonCode.phone_banned)
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_banned.value).inc()
            log.warning("event=verify_account_failed reason=phone_banned %s", ctx)
            _broadcast_account_update(account)

        except (SessionRevoked, AuthKeyUnregistered):
            account.status = TelegramAccountStatus.error
            account.session_encrypted = None
            account.last_error = "Session revoked or auth key unregistered"
            account.release_verify_lease(VerifyStatus.failed, VerifyReasonCode.session_revoked)
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.session_revoked.value).inc()
            log.warning("event=verify_account_failed reason=session_revoked %s", ctx)
            _broadcast_account_update(account)

        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            elapsed = time.monotonic() - t0

            reason = VerifyReasonCode.network if _is_network_error(exc) else VerifyReasonCode.unknown
            if reason == VerifyReasonCode.network and proxy:
                _mark_proxy_unhealthy(proxy, db)

            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            account.release_verify_lease(VerifyStatus.failed, reason)
            db.commit()
            verify_fail_total.labels(reason=reason.value).inc()
            verify_account_duration_seconds.observe(elapsed)
            log.exception(
                "event=verify_account_failed reason=%s %s error=%s elapsed_ms=%d",
                reason.value, ctx, err_msg, int(elapsed * 1000),
            )
            _broadcast_account_update(account)

        finally:
            active_verifications.dec()
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=10)
                except Exception:
                    pass


@celery_app.task(
    name="app.workers.tg_auth_tasks.verify_account_task",
    bind=True,
    soft_time_limit=300,
    time_limit=360,
)
def verify_account_task(self, account_id: int) -> None:
    """Celery wrapper for verify_account with lease-based idempotency."""
    task_id = self.request.id or str(uuid.uuid4())
    logger.info(
        "event=verify_account_task_started account_id=%s task_id=%s",
        account_id, task_id,
    )
    try:
        asyncio.run(_run_verify_account(account_id, task_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s)", task_id, account_id)
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if account:
                account.status = TelegramAccountStatus.error
                account.last_error = "Verification timed out"
                account.release_verify_lease(VerifyStatus.failed, VerifyReasonCode.unknown)
                db.commit()
        return
    logger.info(
        "event=verify_account_task_finished account_id=%s task_id=%s",
        account_id, task_id,
    )
