"""Celery tasks for Telegram account authentication flow.

Each task handles one step of the OTP sign-in flow:
  send_code  -> confirm_code -> (optionally) confirm_password
"""

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta, timezone

from pyrogram import Client
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
from app.core.settings import get_settings
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
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


# ─── send_code ───────────────────────────────────────────────────────

async def _run_send_code(account_id: int, flow_id: str) -> None:
    t0 = time.monotonic()
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            logger.warning(
                "send_code: not found | account_id=%s flow_id=%s",
                account_id, flow_id,
            )
            return

        masked = _mask_phone(account.phone_e164)
        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None

        try:
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)
        except TelegramClientDisabledError:
            flow.state = AuthFlowState.failed
            flow.last_error = "Telegram client disabled"
            account.status = TelegramAccountStatus.error
            account.last_error = "Telegram client disabled"
            db.commit()
            logger.warning(
                "send_code: client disabled | account_id=%s flow_id=%s phone=%s",
                account_id, flow_id, masked,
            )
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
            return

        try:
            await client.connect()
            sent_code = await client.send_code(account.phone_e164)

            flow.state = AuthFlowState.wait_code
            flow.sent_at = datetime.now(timezone.utc)
            flow.expires_at = datetime.now(timezone.utc) + timedelta(seconds=settings.auth_flow_ttl_seconds)
            flow.meta_json = {"phone_code_hash": sent_code.phone_code_hash}

            account.status = TelegramAccountStatus.code_sent
            account.last_error = None
            db.commit()

            elapsed = int((time.monotonic() - t0) * 1000)
            logger.info(
                "send_code: OK | account_id=%s flow_id=%s phone=%s "
                "type=%s elapsed_ms=%s",
                account_id, flow_id, masked,
                getattr(sent_code, "type", "unknown"), elapsed,
            )

            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneNumberInvalid:
            flow.state = AuthFlowState.failed
            flow.last_error = "Invalid phone number"
            account.status = TelegramAccountStatus.error
            account.last_error = "Invalid phone number"
            db.commit()
            logger.warning(
                "send_code: PhoneNumberInvalid | account_id=%s flow_id=%s phone=%s",
                account_id, flow_id, masked,
            )
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        except FloodWait as exc:
            flow.state = AuthFlowState.failed
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            account.last_error = f"FloodWait: {exc.value}s"
            db.commit()
            logger.warning(
                "send_code: FloodWait | account_id=%s flow_id=%s phone=%s wait=%ss",
                account_id, flow_id, masked, exc.value,
            )
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            logger.exception(
                "send_code: FAILED | account_id=%s flow_id=%s phone=%s error=%s",
                account_id, flow_id, masked, err_msg,
            )
            flow.state = AuthFlowState.failed
            flow.last_error = err_msg
            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


@celery_app.task(bind=True, max_retries=2)
def send_code_task(self, account_id: int, flow_id: str) -> None:
    logger.info("send_code_task started | account_id=%s flow_id=%s", account_id, flow_id)
    asyncio.run(_run_send_code(account_id, flow_id))
    logger.info("send_code_task finished | account_id=%s flow_id=%s", account_id, flow_id)


# ─── confirm_code ────────────────────────────────────────────────────

async def _run_confirm_code(account_id: int, flow_id: str, code: str) -> None:
    t0 = time.monotonic()
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            logger.warning("confirm_code: not found account=%s flow=%s", account_id, flow_id)
            return

        masked = _mask_phone(account.phone_e164)

        if flow.state not in (AuthFlowState.wait_code, AuthFlowState.code_sent):
            flow.last_error = f"Invalid flow state: {flow.state}"
            db.commit()
            logger.warning(
                "confirm_code: bad state=%s | account_id=%s flow_id=%s",
                flow.state, account_id, flow_id,
            )
            return

        if flow.expires_at and flow.expires_at < datetime.now(timezone.utc):
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

        try:
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)
        except TelegramClientDisabledError:
            flow.state = AuthFlowState.failed
            flow.last_error = "Telegram client disabled"
            db.commit()
            return

        phone_code_hash = (flow.meta_json or {}).get("phone_code_hash", "")

        try:
            await client.connect()
            # Re-send code to re-establish connection context, then sign in
            try:
                sent_code = await client.send_code(account.phone_e164)
                phone_code_hash = sent_code.phone_code_hash
            except Exception:
                pass  # May fail if code was already sent recently

            signed_in = await client.sign_in(
                phone_number=account.phone_e164,
                phone_code_hash=phone_code_hash,
                phone_code=code,
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
            logger.info(
                "confirm_code: OK | account_id=%s flow_id=%s phone=%s elapsed_ms=%s",
                account_id, flow_id, masked, elapsed,
            )

            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except SessionPasswordNeeded:
            account.status = TelegramAccountStatus.password_required
            account.last_error = None
            flow.state = AuthFlowState.wait_password
            flow.last_error = None

            # Save the partial session so we can continue with password
            try:
                session_string = await client.export_session_string()
                account.session_encrypted = encrypt_session(session_string)
            except Exception:
                pass

            db.commit()
            logger.info(
                "confirm_code: 2FA required | account_id=%s flow_id=%s phone=%s",
                account_id, flow_id, masked,
            )
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneCodeInvalid:
            flow.last_error = "Invalid verification code"
            account.last_error = "Invalid verification code"
            db.commit()
            logger.warning(
                "confirm_code: PhoneCodeInvalid | account_id=%s flow_id=%s",
                account_id, flow_id,
            )
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except PhoneCodeExpired:
            flow.state = AuthFlowState.expired
            flow.last_error = "Verification code expired"
            account.status = TelegramAccountStatus.error
            account.last_error = "Verification code expired"
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except FloodWait as exc:
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            account.last_error = f"FloodWait: {exc.value}s"
            db.commit()
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            logger.exception(
                "confirm_code: FAILED | account_id=%s flow_id=%s error=%s",
                account_id, flow_id, err_msg,
            )
            flow.state = AuthFlowState.failed
            flow.last_error = err_msg
            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


@celery_app.task(bind=True, max_retries=1)
def confirm_code_task(self, account_id: int, flow_id: str, code: str) -> None:
    logger.info("confirm_code_task started | account_id=%s flow_id=%s", account_id, flow_id)
    asyncio.run(_run_confirm_code(account_id, flow_id, code))
    logger.info("confirm_code_task finished | account_id=%s flow_id=%s", account_id, flow_id)


# ─── confirm_password (2FA) ─────────────────────────────────────────

async def _run_confirm_password(account_id: int, flow_id: str, password: str) -> None:
    t0 = time.monotonic()
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        flow = db.get(TelegramAuthFlow, flow_id)
        if not account or not flow:
            logger.warning("confirm_password: not found account=%s flow=%s", account_id, flow_id)
            return

        masked = _mask_phone(account.phone_e164)

        if flow.state != AuthFlowState.wait_password:
            flow.last_error = f"Invalid flow state for password: {flow.state}"
            db.commit()
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

        try:
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)
        except TelegramClientDisabledError:
            flow.state = AuthFlowState.failed
            flow.last_error = "Telegram client disabled"
            db.commit()
            return

        try:
            await client.connect()
            await client.check_password(password)

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
            logger.info(
                "confirm_password: OK | account_id=%s flow_id=%s phone=%s elapsed_ms=%s",
                account_id, flow_id, masked, elapsed,
            )

            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except BadRequest as exc:
            if "PASSWORD_HASH_INVALID" in str(exc):
                flow.last_error = "Invalid 2FA password"
                account.last_error = "Invalid 2FA password"
            else:
                flow.last_error = str(exc)[:500]
                account.last_error = str(exc)[:500]
            db.commit()
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except FloodWait as exc:
            flow.last_error = f"FloodWait: retry after {exc.value}s"
            account.last_error = f"FloodWait: {exc.value}s"
            db.commit()
            _broadcast_flow_update(flow, account_id, account.owner_user_id)

        except Exception as exc:
            err_msg = _sanitize_error(str(exc)[:500])
            logger.exception(
                "confirm_password: FAILED | account_id=%s flow_id=%s error=%s",
                account_id, flow_id, err_msg,
            )
            flow.state = AuthFlowState.failed
            flow.last_error = err_msg
            account.status = TelegramAccountStatus.error
            account.last_error = err_msg
            db.commit()
            _broadcast_account_update(account)
            _broadcast_flow_update(flow, account_id, account.owner_user_id)
        finally:
            try:
                await client.disconnect()
            except Exception:
                pass


@celery_app.task(bind=True, max_retries=1)
def confirm_password_task(self, account_id: int, flow_id: str, password: str) -> None:
    logger.info("confirm_password_task started | account_id=%s flow_id=%s", account_id, flow_id)
    asyncio.run(_run_confirm_password(account_id, flow_id, password))
    logger.info("confirm_password_task finished | account_id=%s flow_id=%s", account_id, flow_id)
