"""Legacy Celery tasks for Telegram send_code / confirm_code (DEPRECATED).

Extracted from tg_auth_tasks.py — kept only for backward compatibility
with tasks already sitting in the Celery queue at the time of deployment.
New auth flows use unified_auth_task instead.
"""

import asyncio
import base64
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

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.core.metrics import verify_fail_total
from app.core.settings import get_settings
from app.core.tz import is_expired, utcnow
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
    _PRE_AUTH_DIR,
    _broadcast_account_update,
    _broadcast_flow_update,
    _cleanup_pre_auth_session,
    _ensure_pre_auth_dir,
    _extract_migrate_dc,
    _get_dc_id,
    _handle_floodwait,
    _is_dc_migrate_error,
    _is_network_error,
    _log_client_fingerprint,
    _mark_proxy_unhealthy,
    _mask_phone,
    _pre_auth_session_name,
    _pre_auth_session_path,
    _read_session_auth_key,
    _sanitize_error,
    _set_dc_id,
)

logger = logging.getLogger(__name__)
settings = get_settings()


# ─── send_code (DEPRECATED — use unified_auth_task) ─────────────────
# Kept for backward compatibility with tasks already in the Celery queue
# at the time of deployment.  New flows use unified_auth_task instead.

async def _run_send_code(account_id: int, flow_id: str) -> None:
    t0 = time.monotonic()
    log = logger.getChild("send_code")
    ctx = {"account_id": account_id, "flow_id": flow_id}

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            log.warning("event=send_code_not_found %s", ctx)
            return

        masked = _mask_phone(account.phone_e164)
        ctx["phone"] = masked
        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None

        client = None
        try:
            log.info("event=send_code_started %s", ctx)

            t_client = time.monotonic()
            _ensure_pre_auth_dir()
            client = create_tg_account_client(
                account, proxy,
                phone=account.phone_e164,
                workdir=str(_PRE_AUTH_DIR),
                session_name=_pre_auth_session_name(flow_id),
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

            t_send = time.monotonic()
            sent_code = await asyncio.wait_for(client.send_code(account.phone_e164), timeout=30)
            dc_after = await _get_dc_id(client)
            log.info(
                "event=telegram_send_code_ok %s type=%s dc_before=%s dc_after=%s elapsed_ms=%d",
                ctx, getattr(sent_code, "type", "unknown"),
                dc_before, dc_after,
                int((time.monotonic() - t_send) * 1000),
            )

            flow.state = AuthFlowState.wait_code
            flow.sent_at = datetime.now(timezone.utc)
            flow.expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_flow_ttl_seconds)
            # Read raw session file and encode as base64 for transport.
            # export_session_string() crashes on pre-auth sessions because
            # dc_id / user_id may be None inside storage (not yet authorized).
            session_path = _pre_auth_session_path(flow_id)
            with open(session_path, "rb") as f:
                session_bytes = f.read()
            session_b64 = base64.b64encode(session_bytes).decode()
            log.info(
                "event=send_code_session_exported %s session_b64_len=%d",
                ctx, len(session_b64),
            )
            meta: dict = {
                "phone_code_hash": sent_code.phone_code_hash,
                "dc_id": str(dc_after),
                "pre_auth_session": session_b64,
            }
            flow.meta_json = meta

            account.status = TelegramAccountStatus.code_sent
            account.last_error = None

            t_commit = time.monotonic()
            db.commit()
            log.info(
                "event=db_commit %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_commit) * 1000),
            )

            elapsed = int((time.monotonic() - t0) * 1000)
            log.info("event=send_code_ok %s elapsed_ms=%d", ctx, elapsed)

            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except TelegramClientDisabledError:
            flow.state = AuthFlowState.failed
            flow.last_error = "Telegram client disabled"
            account.status = TelegramAccountStatus.error
            account.last_error = "Telegram client disabled"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.client_disabled.value).inc()
            log.warning("event=send_code_failed reason=client_disabled %s", ctx)
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        except PhoneNumberInvalid:
            flow.state = AuthFlowState.failed
            flow.last_error = "Invalid phone number"
            account.status = TelegramAccountStatus.error
            account.last_error = "Invalid phone number"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_invalid.value).inc()
            log.warning("event=send_code_failed reason=phone_invalid %s", ctx)
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        except FloodWait as exc:
            flow.state = AuthFlowState.failed
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            _handle_floodwait(account, exc, db)
            verify_fail_total.labels(reason=VerifyReasonCode.floodwait.value).inc()
            log.warning("event=send_code_failed reason=flood_wait wait_s=%s %s", exc.value, ctx)
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        except PhoneNumberBanned:
            flow.state = AuthFlowState.failed
            flow.last_error = "Phone number is banned by Telegram"
            account.status = TelegramAccountStatus.banned
            account.last_error = "Phone number is banned by Telegram"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_banned.value).inc()
            log.warning("event=send_code_failed reason=phone_banned %s", ctx)
            _cleanup_pre_auth_session(flow_id, log)
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
            log.warning("event=send_code_failed reason=session_revoked %s", ctx)
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            elapsed = int((time.monotonic() - t0) * 1000)

            reason = VerifyReasonCode.network if _is_network_error(exc) else VerifyReasonCode.unknown
            if reason == VerifyReasonCode.network and proxy:
                _mark_proxy_unhealthy(proxy, db)

            log.exception(
                "event=send_code_failed reason=%s %s error=%s elapsed_ms=%d",
                reason.value, ctx, err_msg, elapsed,
            )
            flow.state = AuthFlowState.failed
            flow.last_error = err_msg
            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            db.commit()
            verify_fail_total.labels(reason=reason.value).inc()
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        finally:
            if client is not None:
                try:
                    await asyncio.wait_for(client.disconnect(), timeout=10)
                except Exception:
                    pass

            # ── Diagnostic: dump auth_key written by send_code ──
            session_path = _pre_auth_session_path(flow_id)
            ak_info = _read_session_auth_key(session_path, log)
            log.info(
                "event=send_code_session_after_disconnect %s "
                "session_exists=%s session_size=%s "
                "dc_id=%s auth_key_len=%s auth_key_prefix=%s",
                ctx,
                ak_info.get("exists"),
                ak_info.get("size"),
                ak_info.get("dc_id"),
                ak_info.get("auth_key_len"),
                ak_info.get("auth_key_prefix"),
            )


@celery_app.task(
    name="app.workers.tg_auth_tasks.send_code_task",
    bind=True,
    soft_time_limit=300,
    time_limit=360,
)
def send_code_task(self, account_id: int, flow_id: str) -> None:  # DEPRECATED
    """Deprecated: kept for tasks already in queue. New flows use unified_auth_task."""
    logger.info(
        "event=send_code_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    try:
        asyncio.run(_run_send_code(account_id, flow_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s, flow_id=%s)", self.request.id, account_id, flow_id)
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
        "event=send_code_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )


# ─── confirm_code (DEPRECATED — use unified_auth_task) ──────────────
# Kept for backward compatibility with tasks already in the Celery queue
# at the time of deployment.  New flows use unified_auth_task instead.

async def _run_confirm_code(account_id: int, flow_id: str, code: str) -> None:
    t0 = time.monotonic()
    log = logger.getChild("confirm_code")
    ctx = {"account_id": account_id, "flow_id": flow_id}

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            log.warning("event=confirm_code_not_found %s", ctx)
            return

        masked = _mask_phone(account.phone_e164)
        ctx["phone"] = masked

        if flow.state not in (AuthFlowState.wait_code, AuthFlowState.code_sent):
            flow.last_error = f"Invalid flow state: {flow.state}"
            db.commit()
            log.warning("event=confirm_code_bad_state state=%s %s", flow.state, ctx)
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
            account.last_error = "Too many verification attempts"
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        meta = flow.meta_json or {}
        phone_code_hash = meta.get("phone_code_hash", "")

        if not phone_code_hash:
            log.warning("event=confirm_code_missing_hash %s", ctx)
            flow.state = AuthFlowState.failed
            flow.last_error = "Missing phone_code_hash; please resend code"
            account.status = TelegramAccountStatus.error
            account.last_error = "Missing phone_code_hash; please resend code"
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        send_code_dc = meta.get("dc_id", "unknown")
        session_b64 = meta.get("pre_auth_session", "")
        log.info(
            "event=confirm_code_session_info %s send_code_dc=%s "
            "has_session_b64=%s session_b64_len=%d",
            ctx, send_code_dc,
            bool(session_b64), len(session_b64 or ""),
        )

        if not session_b64:
            log.warning("event=confirm_code_missing_session %s", ctx)
            flow.state = AuthFlowState.failed
            flow.last_error = "Missing pre_auth_session; please resend code"
            account.status = TelegramAccountStatus.error
            account.last_error = "Missing pre_auth_session; please resend code"
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        # Restore raw session file from base64 so Pyrogram loads the
        # exact same auth_key that was negotiated during send_code.
        _ensure_pre_auth_dir()
        session_path = _pre_auth_session_path(flow_id)
        session_bytes = base64.b64decode(session_b64)
        with open(session_path, "wb") as f:
            f.write(session_bytes)
        log.info(
            "event=confirm_code_session_restored %s session_file_size=%d",
            ctx, len(session_bytes),
        )

        client = None
        try:
            log.info("event=confirm_code_started %s", ctx)
            client = create_tg_account_client(
                account, proxy,
                workdir=str(_PRE_AUTH_DIR),
                session_name=_pre_auth_session_name(flow_id),
            )

            t_connect = time.monotonic()
            await asyncio.wait_for(client.connect(), timeout=30)
            confirm_dc = await _get_dc_id(client)
            log.info(
                "event=client_connected %s dc_id=%s send_code_dc=%s "
                "session_source=meta_json elapsed_ms=%d",
                ctx, confirm_dc, send_code_dc,
                int((time.monotonic() - t_connect) * 1000),
            )
            _log_client_fingerprint(log, ctx, client)

            # ── Diagnostic: verify hash stability ──
            log.info(
                "event=confirm_code_hash_check %s hash_len=%d hash_prefix=%s",
                ctx, len(phone_code_hash), phone_code_hash[:8],
            )

            # ── Diagnostic: payload entering sign_in ──
            log.info(
                "event=confirm_code_payload %s code_len=%d code_is_digits=%s hash_prefix=%s flow_state=%s dc_id=%s",
                ctx,
                len(code or ""),
                bool(code) and code.isdigit(),
                phone_code_hash[:8],
                flow.state,
                confirm_dc,
            )

            # ── sign_in with one-retry on DC-migrate error ──
            t_sign = time.monotonic()
            try:
                signed_in = await asyncio.wait_for(client.sign_in(
                    phone_number=account.phone_e164,
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
                    "event=sign_in_dc_migrate target_dc=%d %s", target_dc, ctx,
                )
                await asyncio.wait_for(client.disconnect(), timeout=10)
                await _set_dc_id(client, target_dc)
                await asyncio.wait_for(client.connect(), timeout=30)
                signed_in = await asyncio.wait_for(client.sign_in(
                    phone_number=account.phone_e164,
                    phone_code_hash=phone_code_hash,
                    phone_code=code,
                ), timeout=30)
            log.info(
                "event=sign_in_ok %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_sign) * 1000),
            )

            # Success - save session
            session_string = await asyncio.wait_for(client.export_session_string(), timeout=15)
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

            elapsed = int((time.monotonic() - t0) * 1000)
            log.info("event=confirm_code_ok %s elapsed_ms=%d", ctx, elapsed)

            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except SessionPasswordNeeded:
            account.status = TelegramAccountStatus.password_required
            account.last_error = None
            flow.state = AuthFlowState.wait_password
            flow.last_error = None
            # Extend TTL so the user has time to enter the 2FA password
            flow.expires_at = utcnow() + timedelta(seconds=settings.auth_flow_ttl_seconds)

            # Save the partial session so we can continue with password
            if client is not None:
                try:
                    session_string = await asyncio.wait_for(client.export_session_string(), timeout=15)
                    account.session_encrypted = encrypt_session(session_string)
                except Exception:
                    pass

            db.commit()
            log.info("event=confirm_code_2fa_required %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneCodeInvalid:
            flow.last_error = "Invalid verification code"
            account.last_error = "Invalid verification code"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.invalid_code.value).inc()
            log.warning("event=confirm_code_failed reason=code_invalid %s", ctx)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneCodeExpired:
            flow.state = AuthFlowState.expired
            flow.last_error = (
                "PhoneCodeExpired: Telegram server rejected the code "
                "(session mismatch or server-side timeout)"
            )
            account.status = TelegramAccountStatus.error
            account.last_error = "PhoneCodeExpired (Telegram server rejected the code)"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.code_expired.value).inc()
            log.warning(
                "event=confirm_code_failed reason=phone_code_expired %s "
                "session_b64_was_provided=%s",
                ctx, bool(session_b64),
            )
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except FloodWait as exc:
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            _handle_floodwait(account, exc, db)
            verify_fail_total.labels(reason=VerifyReasonCode.floodwait.value).inc()
            log.warning("event=confirm_code_failed reason=flood_wait wait_s=%s %s", exc.value, ctx)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneNumberBanned:
            flow.state = AuthFlowState.failed
            flow.last_error = "Phone number is banned by Telegram"
            account.status = TelegramAccountStatus.banned
            account.last_error = "Phone number is banned by Telegram"
            db.commit()
            verify_fail_total.labels(reason=VerifyReasonCode.phone_banned.value).inc()
            log.warning("event=confirm_code_failed reason=phone_banned %s", ctx)
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
            log.warning("event=confirm_code_failed reason=session_revoked %s", ctx)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            elapsed = int((time.monotonic() - t0) * 1000)

            reason = VerifyReasonCode.network if _is_network_error(exc) else VerifyReasonCode.unknown
            if reason == VerifyReasonCode.network and proxy:
                _mark_proxy_unhealthy(proxy, db)

            log.exception(
                "event=confirm_code_failed reason=%s %s error=%s elapsed_ms=%d",
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
            _cleanup_pre_auth_session(flow_id, log)


@celery_app.task(
    name="app.workers.tg_auth_tasks.confirm_code_task",
    bind=True,
    soft_time_limit=300,
    time_limit=360,
)
def confirm_code_task(self, account_id: int, flow_id: str, code: str) -> None:  # DEPRECATED
    """Deprecated: kept for tasks already in queue. New flows use unified_auth_task."""
    logger.info(
        "event=confirm_code_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    try:
        asyncio.run(_run_confirm_code(account_id, flow_id, code))
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
        "event=confirm_code_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )
