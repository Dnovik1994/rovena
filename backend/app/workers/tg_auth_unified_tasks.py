"""Unified Telegram authentication task (single-connection send_code + sign_in).

Extracted from tg_auth_tasks.py — the main auth flow (~470 lines).
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta, timezone

from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import (
    AuthKeyUnregistered,
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberBanned,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
    SessionRevoked,
)
from sqlalchemy import select

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.core.metrics import verify_fail_total
from app.core.settings import get_settings
from app.core.tz import utcnow
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
    _cleanup_pre_auth_session,
    _extract_migrate_dc,
    _get_dc_id,
    _handle_floodwait,
    _is_dc_migrate_error,
    _is_network_error,
    _log_client_fingerprint,
    _mark_proxy_unhealthy,
    _mask_phone,
    _sanitize_error,
    _set_dc_id,
)

logger = logging.getLogger(__name__)
settings = get_settings()


async def _export_session(client, flow_id: str, log) -> str:
    """Export session string, falling back to file-based session read.

    Pyrogram's ``export_session_string()`` works reliably for in-memory
    sessions.  For file-based sessions it may raise *"required argument is
    not an integer"*.  The fallback reads the SQLite session file directly
    and packs the data into the Pyrogram session-string format.
    """
    try:
        return await asyncio.wait_for(client.export_session_string(), timeout=15)
    except Exception as exc:
        log.warning("export_session_string failed (%s), reading from file", exc)

    # Fallback: read SQLite session file directly
    import base64
    import sqlite3
    import struct
    from pathlib import Path

    session_path = Path(f"/data/pyrogram_pre_auth/preauth-{flow_id}.session")
    if not session_path.exists():
        raise RuntimeError(f"Session file not found: {session_path}")

    conn = sqlite3.connect(str(session_path))
    try:
        row = conn.execute(
            "SELECT dc_id, api_id, test_mode, auth_key, date, user_id, is_bot "
            "FROM sessions"
        ).fetchone()
        if not row:
            raise RuntimeError("No session data in SQLite file")

        dc_id, api_id, test_mode, auth_key, date, user_id, is_bot = row

        packed = struct.pack(
            ">B?256sI?",
            dc_id,
            test_mode,
            auth_key,
            user_id or 0,
            is_bot or False,
        )
        return base64.urlsafe_b64encode(packed).decode().rstrip("=")
    finally:
        conn.close()


# ─── unified_auth (single-connection send_code + sign_in) ───────────

async def _run_unified_auth(account_id: int, flow_id: str) -> None:
    """Send code and sign in within a single Pyrogram connection.

    Pyrogram 2.0.106 overwrites the auth_key on every ``client.connect()``
    for file-based sessions that haven't completed authorisation.  This makes
    it impossible to split send_code / sign_in into two separate Celery tasks
    with separate connections.

    This function keeps ONE connection alive, polls the DB for the code
    submitted by the frontend, and calls ``sign_in`` on the same session.
    """
    t0 = time.monotonic()
    log = logger.getChild("unified_auth")
    ctx = {"account_id": account_id, "flow_id": flow_id}

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            log.warning("event=unified_auth_not_found %s", ctx)
            return

        masked = _mask_phone(account.phone_e164)
        ctx["phone"] = masked
        phone_number = account.phone_e164
        owner_user_id = account.owner_user_id
        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None

        client = None
        try:
            log.info("event=unified_auth_started %s", ctx)

            # ── Phase 1: Create client & connect (ONCE) ──────────────
            # Use in_memory=True (default) — unified auth keeps the
            # connection alive in a single task, so file persistence
            # is unnecessary.  File-based sessions caused
            # export_session_string() to crash with "required argument
            # is not an integer" in Pyrogram 2.0.106.
            t_client = time.monotonic()
            client = create_tg_account_client(
                account, proxy,
                phone=phone_number,
            )
            log.info(
                "event=client_created %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_client) * 1000),
            )

            t_connect = time.monotonic()
            await asyncio.wait_for(client.connect(), timeout=30)
            dc_before = await _get_dc_id(client)
            log.info(
                "event=client_connected %s dc_id=%s elapsed_ms=%d",
                ctx, dc_before, int((time.monotonic() - t_connect) * 1000),
            )
            _log_client_fingerprint(log, ctx, client)

            # ── Phase 2: Send code ───────────────────────────────────
            t_send = time.monotonic()
            sent_code = await asyncio.wait_for(client.send_code(phone_number), timeout=30)
            dc_after = await _get_dc_id(client)
            log.info(
                "event=telegram_send_code_ok %s type=%s dc_before=%s dc_after=%s elapsed_ms=%d",
                ctx, getattr(sent_code, "type", "unknown"),
                dc_before, dc_after,
                int((time.monotonic() - t_send) * 1000),
            )

            phone_code_hash = sent_code.phone_code_hash

            flow.state = AuthFlowState.wait_code
            flow.sent_at = datetime.now(timezone.utc)
            flow.expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=settings.auth_flow_ttl_seconds,
            )
            flow.meta_json = {
                "phone_code_hash": phone_code_hash,
                "dc_id": str(dc_after),
            }
            account.status = TelegramAccountStatus.code_sent
            account.last_error = None
            db.commit()

            log.info("event=unified_auth_code_sent %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)

            # ── Phase 3: Poll DB for submitted code ──────────────────
            poll_start = time.monotonic()
            max_poll_seconds = 280  # slightly less than flow TTL (300s)
            poll_count = 0

            code = None
            while True:
                poll_count += 1
                elapsed_poll = time.monotonic() - poll_start
                if elapsed_poll >= max_poll_seconds:
                    flow.state = AuthFlowState.expired
                    flow.last_error = "No code submitted within timeout"
                    account.status = TelegramAccountStatus.error
                    account.last_error = "Verification flow expired — no code submitted"
                    db.commit()
                    log.info("event=unified_auth_poll_timeout %s elapsed=%.0f", ctx, elapsed_poll)
                    _broadcast_account_update(account)
                    _broadcast_flow_update(flow, account_id, owner_user_id)
                    return

                # Close current transaction so next SELECT sees fresh data
                # (MySQL REPEATABLE-READ returns snapshot from first read).
                db.commit()
                row = db.execute(
                    select(TelegramAuthFlow.state, TelegramAuthFlow.meta_json)
                    .where(TelegramAuthFlow.id == flow_id)
                ).first()
                if not row:
                    log.warning("event=unified_auth_flow_disappeared %s", ctx)
                    return
                current_state = row.state
                current_meta = row.meta_json or {}

                if poll_count % 5 == 0:
                    log.info(
                        "event=unified_auth_polling %s poll_count=%d elapsed=%d state=%s",
                        ctx, poll_count, int(elapsed_poll), current_state,
                    )

                if current_state == AuthFlowState.code_submitted:
                    code = current_meta.get("submitted_code")
                    if code:
                        # Sync the ORM object so subsequent writes are consistent
                        db.expire(flow)
                        db.refresh(flow)
                        log.info("event=unified_auth_code_received %s", ctx)
                        break
                elif current_state in (AuthFlowState.expired, AuthFlowState.failed):
                    log.info(
                        "event=unified_auth_flow_terminated state=%s %s",
                        current_state, ctx,
                    )
                    return

                await asyncio.sleep(3)

            # ── Phase 4: sign_in (with retry on PhoneCodeInvalid) ────
            while True:
                flow.attempts += 1
                if flow.attempts > settings.auth_flow_max_attempts:
                    flow.state = AuthFlowState.failed
                    flow.last_error = "Too many attempts"
                    account.status = TelegramAccountStatus.error
                    account.last_error = "Too many verification attempts"
                    db.commit()
                    log.warning("event=unified_auth_too_many_attempts %s", ctx)
                    _broadcast_account_update(account)
                    _broadcast_flow_update(flow, account_id, owner_user_id)
                    return

                try:
                    t_sign = time.monotonic()
                    try:
                        signed_in = await asyncio.wait_for(client.sign_in(
                            phone_number=phone_number,
                            phone_code_hash=phone_code_hash,
                            phone_code=code,
                        ), timeout=30)
                    except asyncio.TimeoutError:
                        raise
                    except Exception as sign_exc:
                        if not _is_dc_migrate_error(sign_exc):
                            raise
                        target_dc = _extract_migrate_dc(sign_exc)
                        if target_dc is None:
                            raise
                        log.warning(
                            "event=sign_in_dc_migrate target_dc=%d %s",
                            target_dc, ctx,
                        )
                        await asyncio.wait_for(client.disconnect(), timeout=10)
                        await _set_dc_id(client, target_dc)
                        await asyncio.wait_for(client.connect(), timeout=30)
                        signed_in = await asyncio.wait_for(client.sign_in(
                            phone_number=phone_number,
                            phone_code_hash=phone_code_hash,
                            phone_code=code,
                        ), timeout=30)

                    log.info(
                        "event=sign_in_ok %s elapsed_ms=%d",
                        ctx, int((time.monotonic() - t_sign) * 1000),
                    )

                    # ── Success — save session ──
                    session_string = await _export_session(client, flow_id, log)
                    account.session_encrypted = encrypt_session(session_string)
                    account.tg_user_id = signed_in.id
                    account.tg_username = getattr(signed_in, "username", None)
                    account.first_name = getattr(signed_in, "first_name", None)
                    account.last_name = getattr(signed_in, "last_name", None)
                    account.status = TelegramAccountStatus.verified
                    account.verified_at = datetime.now(timezone.utc)
                    account.last_seen_at = datetime.now(timezone.utc)
                    account.last_error = None

                    flow.state = AuthFlowState.done
                    flow.last_error = None
                    db.commit()

                    elapsed_total = int((time.monotonic() - t0) * 1000)
                    log.info("event=unified_auth_ok %s elapsed_ms=%d", ctx, elapsed_total)

                    _broadcast_account_update(account)
                    _broadcast_flow_update(flow, account_id, owner_user_id)

                    # Auto-trigger account sync after successful verification
                    try:
                        from app.workers.tg_sync_tasks import sync_account_data
                        sync_account_data.delay(account_id)
                        log.info("event=sync_dispatched_after_auth account_id=%d", account_id)
                    except Exception as sync_exc:
                        log.warning("event=sync_dispatch_failed account_id=%d error=%s", account_id, sync_exc)

                    return

                except SessionPasswordNeeded:
                    # Session export is MANDATORY for confirm_password_task.
                    # Without it, confirm_password creates a new auth_key → session_revoked.
                    try:
                        session_string = await _export_session(client, flow_id, log)
                        account.session_encrypted = encrypt_session(session_string)
                        log.info("event=2fa_session_exported %s", ctx)
                    except Exception as sess_err:
                        log.error("event=2fa_session_export_failed %s error=%s", ctx, sess_err)
                        flow.state = AuthFlowState.failed
                        flow.last_error = f"Failed to export session for 2FA: {sess_err}"
                        account.status = TelegramAccountStatus.error
                        account.last_error = "2FA session export failed, please retry"
                        db.commit()
                        _broadcast_account_update(account)
                        _broadcast_flow_update(flow, account_id, owner_user_id)
                        return

                    account.status = TelegramAccountStatus.password_required
                    account.last_error = None
                    flow.state = AuthFlowState.wait_password
                    flow.last_error = None
                    flow.expires_at = utcnow() + timedelta(
                        seconds=settings.auth_flow_ttl_seconds,
                    )
                    db.commit()
                    log.info("event=unified_auth_2fa_required %s session_saved=True", ctx)
                    _broadcast_account_update(account)
                    _broadcast_flow_update(flow, account_id, owner_user_id)
                    return

                except PhoneCodeInvalid:
                    flow.last_error = "Invalid verification code"
                    account.last_error = "Invalid verification code"
                    flow.state = AuthFlowState.wait_code
                    db.commit()
                    verify_fail_total.labels(reason=VerifyReasonCode.invalid_code.value).inc()
                    log.warning(
                        "event=unified_auth_code_invalid attempt=%d %s",
                        flow.attempts, ctx,
                    )
                    _broadcast_flow_update(flow, account_id, owner_user_id)

                    # Wait for a new code (re-enter poll loop)
                    code = None
                    retry_poll_count = 0
                    while True:
                        retry_poll_count += 1
                        total_elapsed = time.monotonic() - poll_start
                        if total_elapsed >= max_poll_seconds:
                            flow.state = AuthFlowState.expired
                            flow.last_error = "No code submitted within timeout"
                            account.status = TelegramAccountStatus.error
                            account.last_error = "Verification flow expired"
                            db.commit()
                            log.info("event=unified_auth_poll_timeout_retry %s", ctx)
                            _broadcast_account_update(account)
                            _broadcast_flow_update(flow, account_id, owner_user_id)
                            return

                        # Close current transaction so next SELECT sees fresh data
                        # (MySQL REPEATABLE-READ returns snapshot from first read).
                        db.commit()
                        row = db.execute(
                            select(TelegramAuthFlow.state, TelegramAuthFlow.meta_json)
                            .where(TelegramAuthFlow.id == flow_id)
                        ).first()
                        if not row:
                            log.warning("event=unified_auth_flow_disappeared_retry %s", ctx)
                            return
                        current_state = row.state
                        current_meta = row.meta_json or {}

                        if retry_poll_count % 5 == 0:
                            log.info(
                                "event=unified_auth_polling_retry %s poll_count=%d elapsed=%d state=%s",
                                ctx, retry_poll_count, int(total_elapsed), current_state,
                            )

                        if current_state == AuthFlowState.code_submitted:
                            code = current_meta.get("submitted_code")
                            if code:
                                db.expire(flow)
                                db.refresh(flow)
                                log.info("event=unified_auth_retry_code_received %s", ctx)
                                break
                        elif current_state in (AuthFlowState.expired, AuthFlowState.failed):
                            log.info(
                                "event=unified_auth_flow_terminated state=%s %s",
                                current_state, ctx,
                            )
                            return

                        await asyncio.sleep(3)

                    continue  # retry sign_in with new code

                except PhoneCodeExpired:
                    flow.state = AuthFlowState.expired
                    flow.last_error = (
                        "PhoneCodeExpired: Telegram server rejected the code "
                        "(server-side timeout)"
                    )
                    account.status = TelegramAccountStatus.error
                    account.last_error = "PhoneCodeExpired (Telegram server rejected the code)"
                    db.commit()
                    verify_fail_total.labels(reason=VerifyReasonCode.code_expired.value).inc()
                    log.warning("event=unified_auth_code_expired %s", ctx)
                    _broadcast_account_update(account)
                    _broadcast_flow_update(flow, account_id, owner_user_id)
                    return

        # ── Top-level exception handlers (cover both send_code & sign_in phases) ──
        except TelegramClientDisabledError:
            flow.state = AuthFlowState.failed
            flow.last_error = "Telegram client disabled"
            account.status = TelegramAccountStatus.error
            account.last_error = "Telegram client disabled"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.client_disabled.value).inc()
            log.warning("event=unified_auth_failed reason=client_disabled %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)
        except PhoneNumberInvalid:
            flow.state = AuthFlowState.failed
            flow.last_error = "Invalid phone number"
            account.status = TelegramAccountStatus.error
            account.last_error = "Invalid phone number"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_invalid.value).inc()
            log.warning("event=unified_auth_failed reason=phone_invalid %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)
        except FloodWait as exc:
            flow.state = AuthFlowState.failed
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            _handle_floodwait(account, exc, db)
            verify_fail_total.labels(reason=VerifyReasonCode.floodwait.value).inc()
            log.warning("event=unified_auth_failed reason=flood_wait wait_s=%s %s", exc.value, ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)
        except PhoneNumberBanned:
            flow.state = AuthFlowState.failed
            flow.last_error = "Phone number is banned by Telegram"
            account.status = TelegramAccountStatus.banned
            account.last_error = "Phone number is banned by Telegram"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_banned.value).inc()
            log.warning("event=unified_auth_failed reason=phone_banned %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)
        except (SessionRevoked, AuthKeyUnregistered):
            flow.state = AuthFlowState.failed
            flow.last_error = "Session revoked or auth key unregistered"
            account.status = TelegramAccountStatus.error
            account.session_encrypted = None
            account.last_error = "Session revoked or auth key unregistered"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.session_revoked.value).inc()
            log.warning("event=unified_auth_failed reason=session_revoked %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)
        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            elapsed = int((time.monotonic() - t0) * 1000)

            reason = VerifyReasonCode.network if _is_network_error(exc) else VerifyReasonCode.unknown
            if reason == VerifyReasonCode.network and proxy:
                _mark_proxy_unhealthy(proxy, db)

            log.exception(
                "event=unified_auth_failed reason=%s %s error=%s elapsed_ms=%d",
                reason.value, ctx, err_msg, elapsed,
            )
            flow.state = AuthFlowState.failed
            flow.last_error = err_msg
            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            db.commit()
            verify_fail_total.labels(reason=reason.value).inc()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, owner_user_id)
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=10)
                except Exception:
                    pass
            _cleanup_pre_auth_session(flow_id, log)


@celery_app.task(
    name="app.workers.tg_auth_tasks.unified_auth_task",
    bind=True,
    soft_time_limit=330,
    time_limit=360,
)
def unified_auth_task(self, account_id: int, flow_id: str) -> None:
    """Single-connection auth task: send_code + poll for code + sign_in.

    Replaces the two-step send_code_task / confirm_code_task flow to work
    around Pyrogram 2.0.106 overwriting auth_key on every connect() for
    pre-auth file sessions.
    """
    logger.info(
        "event=unified_auth_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    try:
        asyncio.run(_run_unified_auth(account_id, flow_id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "Task %s hit soft time limit, graceful shutdown (account_id=%s, flow_id=%s)",
            self.request.id, account_id, flow_id,
        )
        _cleanup_pre_auth_session(flow_id)
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
        "event=unified_auth_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )
