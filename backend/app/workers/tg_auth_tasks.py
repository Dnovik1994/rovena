"""Celery tasks for Telegram account authentication flow.

Each task handles one step of the OTP sign-in flow:
  send_code  -> confirm_code -> (optionally) confirm_password

Plus a standalone verify_account task that validates existing sessions
with lease-based idempotency.
"""

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.core.tz import ensure_utc, is_expired, utcnow

from pyrogram.errors import (
    BadRequest,
    FloodWait,
    PhoneCodeExpired,
    PhoneCodeInvalid,
    PhoneNumberInvalid,
    SessionPasswordNeeded,
)

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.core.metrics import (
    active_verifications,
    floodwait_seconds_hist,
    proxy_marked_unhealthy_total,
    verify_account_duration_seconds,
    verify_fail_total,
    verify_lease_acquired_total,
    verify_lease_rejected_total,
)
from app.core.settings import get_settings
from app.models.proxy import Proxy, ProxyStatus
from app.models.telegram_account import (
    TelegramAccount,
    TelegramAccountStatus,
    VerifyReasonCode,
    VerifyStatus,
)
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.services.session_crypto import encrypt_session
from app.services.websocket_manager import manager
from app.workers import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

# Configure Redis on the manager so broadcast_sync publishes via Redis
# (Celery workers are separate processes with no WS clients)
if settings.redis_url:
    manager.configure_redis(settings.redis_url)

# ── Max network retries with jitter ──
_MAX_NETWORK_RETRIES = 2


def _mask_phone(phone: str) -> str:
    """Mask phone number for logging (no PII in logs).
    '+380501234567' -> '+380*****4567'
    """
    if not phone or len(phone) < 8:
        return "***"
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


_PHONE_RE = re.compile(r"\+\d{7,15}")


def _sanitize_error(msg: str) -> str:
    """Remove any phone numbers from error messages before logging."""
    return _PHONE_RE.sub("***", msg)


def _broadcast_account_update(account: TelegramAccount) -> None:
    manager.broadcast_sync({
        "type": "account_status_changed",
        "user_id": account.owner_user_id,
        "account_id": account.id,
        "status": account.status.value if hasattr(account.status, "value") else str(account.status),
    })


def _broadcast_flow_update(flow: TelegramAuthFlow, account_id: int, owner_user_id: int) -> None:
    manager.broadcast_sync({
        "type": "auth_flow_updated",
        "user_id": owner_user_id,
        "account_id": account_id,
        "flow_id": flow.id,
        "state": flow.state.value if hasattr(flow.state, "value") else str(flow.state),
    })


def _handle_floodwait(account: TelegramAccount, exc: FloodWait, db) -> None:
    """Unified FloodWait handling: set cooldown + record metrics."""
    wait_s = int(exc.value)
    floodwait_seconds_hist.observe(wait_s)
    account.status = TelegramAccountStatus.cooldown
    account.cooldown_until = utcnow() + timedelta(seconds=wait_s)
    account.last_error = f"FloodWait: {wait_s}s"
    db.commit()


def _mark_proxy_unhealthy(proxy: Proxy | None, db) -> None:
    """Mark proxy as errored when it causes connection failures."""
    if proxy is None:
        return
    proxy.status = ProxyStatus.error
    proxy.last_check = utcnow()
    db.commit()
    proxy_marked_unhealthy_total.inc()


def _is_network_error(exc: Exception) -> bool:
    """Heuristic to identify network/timeout errors."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("timeout", "connection", "network", "eof", "reset", "refused"))


def _log_client_fingerprint(log, ctx, client) -> None:
    """Log Telegram client session identity for cross-step consistency checks."""
    try:
        session_id = getattr(client, "name", None) or "unknown"
        proxy = getattr(client, "proxy", None) or {}
        if isinstance(proxy, dict):
            proxy_host = "%s:%s" % (proxy.get("hostname", "?"), proxy.get("port", "?"))
        else:
            proxy_host = "none"
        device_model = getattr(client, "device_model", "?")
        system_version = getattr(client, "system_version", "?")
        app_version = getattr(client, "app_version", "?")
        log.info(
            "event=telegram_client_fingerprint %s session=%s proxy=%s device=%s system=%s app=%s",
            ctx, session_id, proxy_host, device_model, system_version, app_version,
        )
    except Exception:
        log.warning("event=telegram_client_fingerprint_error %s", ctx)


async def _get_dc_id(client) -> str:
    """Extract dc_id from a connected Pyrogram client (best-effort)."""
    try:
        dc = client.storage.dc_id
        if callable(dc):
            return str(await dc())
        return str(dc)
    except Exception:
        return "unknown"


def _is_dc_migrate_error(exc: Exception) -> bool:
    return "MIGRATE" in type(exc).__name__.upper() or "MIGRATE" in str(exc).upper()


def _extract_migrate_dc(exc: Exception) -> int | None:
    dc = getattr(exc, "value", None)
    if isinstance(dc, int):
        return dc
    m = re.search(r"MIGRATE[_ ]*(\d+)", str(exc).upper())
    return int(m.group(1)) if m else None


# ── Pre-auth session persistence ─────────────────────────────────────
# File-based Pyrogram sessions persist auth_key between send_code and
# confirm_code Celery tasks, avoiding Telegram PhoneCodeExpired errors
# caused by creating a fresh auth_key on each task invocation.

_PRE_AUTH_DIR = Path(os.environ.get("PRE_AUTH_SESSION_DIR", "/data/pyrogram_pre_auth"))


def _pre_auth_session_name(flow_id: str) -> str:
    """Deterministic Pyrogram session name tied to auth flow."""
    return f"preauth-{flow_id}"


def _pre_auth_session_path(flow_id: str) -> Path:
    """Full path to the pre-auth SQLite session file."""
    return _PRE_AUTH_DIR / f"{_pre_auth_session_name(flow_id)}.session"


def _ensure_pre_auth_dir() -> None:
    """Create pre-auth session directory if it doesn't exist.

    Logs diagnostics and raises RuntimeError with an actionable message
    when the directory cannot be created or is not writable (e.g. the
    Docker named volume is not mounted).
    """
    _log = logger.getChild("pre_auth_dir")
    _log.info(
        "event=pre_auth_dir_check path=%s exists=%s",
        _PRE_AUTH_DIR, _PRE_AUTH_DIR.exists(),
    )
    try:
        _PRE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.error(
            "event=pre_auth_dir_create_failed path=%s error=%s "
            "hint=ensure 'pre-auth-sessions' volume is mounted in docker-compose.prod.yml",
            _PRE_AUTH_DIR, exc,
        )
        raise RuntimeError(
            f"pre-auth dir not writable: cannot create {_PRE_AUTH_DIR} — "
            f"check that the 'pre-auth-sessions' named volume is mounted "
            f"at {_PRE_AUTH_DIR} in docker-compose.prod.yml"
        ) from exc

    if not os.access(_PRE_AUTH_DIR, os.W_OK):
        _log.error(
            "event=pre_auth_dir_not_writable path=%s "
            "hint=volume may be owned by root; container user must have write access",
            _PRE_AUTH_DIR,
        )
        raise RuntimeError(
            f"pre-auth dir not writable: {_PRE_AUTH_DIR} exists but is not writable — "
            f"check volume permissions for the container user"
        )


def _cleanup_pre_auth_session(flow_id: str, log=None) -> None:
    """Remove temporary pre-auth session file (and SQLite side-files)."""
    base = _pre_auth_session_path(flow_id)
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            (base.parent / (base.name + suffix)).unlink(missing_ok=True)
        except Exception:
            pass
    if log:
        log.info("event=pre_auth_session_cleaned flow_id=%s", flow_id)


# ─── send_code ───────────────────────────────────────────────────────

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
            await client.connect()
            dc_before = await _get_dc_id(client)
            log.info(
                "event=client_connected %s dc_id=%s elapsed_ms=%d",
                ctx, dc_before, int((time.monotonic() - t_connect) * 1000),
            )
            _log_client_fingerprint(log, ctx, client)

            t_send = time.monotonic()
            sent_code = await client.send_code(account.phone_e164)
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
            meta: dict = {"phone_code_hash": sent_code.phone_code_hash, "dc_id": dc_after}
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
                    await client.disconnect()
                except Exception:
                    pass


@celery_app.task(bind=True, max_retries=2)
def send_code_task(self, account_id: int, flow_id: str) -> None:
    logger.info(
        "event=send_code_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    asyncio.run(_run_send_code(account_id, flow_id))
    logger.info(
        "event=send_code_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )


# ─── confirm_code ────────────────────────────────────────────────────

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
        session_path = _pre_auth_session_path(flow_id)
        has_pre_auth_session = session_path.exists()
        log.info(
            "event=confirm_code_session_info %s send_code_dc=%s pre_auth_session=%s session_path=%s",
            ctx, send_code_dc, has_pre_auth_session, session_path,
        )

        client = None
        try:
            log.info("event=confirm_code_started %s", ctx)
            client = create_tg_account_client(
                account, proxy,
                phone=account.phone_e164,
                workdir=str(_PRE_AUTH_DIR),
                session_name=_pre_auth_session_name(flow_id),
            )

            t_connect = time.monotonic()
            await client.connect()
            confirm_dc = await _get_dc_id(client)
            log.info(
                "event=client_connected %s dc_id=%s send_code_dc=%s elapsed_ms=%d",
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
                signed_in = await client.sign_in(
                    phone_number=account.phone_e164,
                    phone_code_hash=phone_code_hash,
                    phone_code=code,
                )
            except Exception as sign_exc:
                if not _is_dc_migrate_error(sign_exc):
                    raise
                target_dc = _extract_migrate_dc(sign_exc)
                if target_dc is None:
                    raise
                log.warning(
                    "event=sign_in_dc_migrate target_dc=%d %s", target_dc, ctx,
                )
                await client.disconnect()
                await client.storage.dc_id(target_dc)
                await client.connect()
                signed_in = await client.sign_in(
                    phone_number=account.phone_e164,
                    phone_code_hash=phone_code_hash,
                    phone_code=code,
                )
            log.info(
                "event=sign_in_ok %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_sign) * 1000),
            )

            # Success - save session
            session_string = await client.export_session_string()
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

            _cleanup_pre_auth_session(flow_id, log)
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
                    session_string = await client.export_session_string()
                    account.session_encrypted = encrypt_session(session_string)
                except Exception:
                    pass

            db.commit()
            log.info("event=confirm_code_2fa_required %s", ctx)
            _cleanup_pre_auth_session(flow_id, log)
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
                "pre_auth_session_existed=%s",
                ctx, has_pre_auth_session,
            )
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except FloodWait as exc:
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            _handle_floodwait(account, exc, db)
            verify_fail_total.labels(reason=VerifyReasonCode.floodwait.value).inc()
            log.warning("event=confirm_code_failed reason=flood_wait wait_s=%s %s", exc.value, ctx)
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
            _cleanup_pre_auth_session(flow_id, log)
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        finally:
            if client is not None:
                try:
                    await client.disconnect()
                except Exception:
                    pass


@celery_app.task(bind=True, max_retries=1)
def confirm_code_task(self, account_id: int, flow_id: str, code: str) -> None:
    logger.info(
        "event=confirm_code_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    asyncio.run(_run_confirm_code(account_id, flow_id, code))
    logger.info(
        "event=confirm_code_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )


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

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None

        client = None
        try:
            log.info("event=confirm_password_started %s", ctx)
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)

            t_connect = time.monotonic()
            await client.connect()
            log.info(
                "event=client_connected %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_connect) * 1000),
            )

            t_check = time.monotonic()
            await client.check_password(password)
            log.info(
                "event=check_password_ok %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_check) * 1000),
            )

            session_string = await client.export_session_string()
            account.session_encrypted = encrypt_session(session_string)

            me = await client.get_me()
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
                    await client.disconnect()
                except Exception:
                    pass


@celery_app.task(bind=True, max_retries=1)
def confirm_password_task(self, account_id: int, flow_id: str, password: str) -> None:
    logger.info(
        "event=confirm_password_task_started account_id=%s flow_id=%s",
        account_id, flow_id,
    )
    asyncio.run(_run_confirm_password(account_id, flow_id, password))
    logger.info(
        "event=confirm_password_task_finished account_id=%s flow_id=%s",
        account_id, flow_id,
    )


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
            await client.connect()
            log.info(
                "event=verify_client_connected %s elapsed_ms=%d",
                ctx, int((time.monotonic() - t_connect) * 1000),
            )

            t_get_me = time.monotonic()
            me = await client.get_me()
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
                    await client.disconnect()
                except Exception:
                    pass


@celery_app.task(bind=True, max_retries=_MAX_NETWORK_RETRIES, default_retry_delay=5)
def verify_account_task(self, account_id: int) -> None:
    """Celery wrapper for verify_account with lease-based idempotency."""
    task_id = self.request.id or str(uuid.uuid4())
    logger.info(
        "event=verify_account_task_started account_id=%s task_id=%s",
        account_id, task_id,
    )
    asyncio.run(_run_verify_account(account_id, task_id))
    logger.info(
        "event=verify_account_task_finished account_id=%s task_id=%s",
        account_id, task_id,
    )
