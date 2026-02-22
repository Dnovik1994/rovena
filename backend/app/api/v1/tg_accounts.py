"""API router for Telegram account management via phone + OTP flow.

All endpoints use synchronous ``def`` so FastAPI runs them in a threadpool,
keeping the async event loop free for WebSocket / background tasks.
"""

import asyncio
import logging
import random
import threading
import time
from datetime import datetime, timedelta, timezone

from app.core.tz import ensure_utc, is_expired

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pyrogram.errors import AuthKeyUnregistered, SessionRevoked, UserDeactivatedBan
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.api.deps import get_tariff_limits
from app.clients.device_generator import generate_device_config
from app.clients.telegram_client import create_tg_account_client
from app.core.database import get_db
from app.core.rbac import require_permission
from app.core.rate_limit import limiter
from app.core.settings import get_settings
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.models.tg_account_chat import TgAccountChat
from app.models.tg_chat_member import TgChatMember
from app.models.tg_user import TgUser
from app.models.user import User
from app.models.telegram_account import VerifyStatus
from app.models.telegram_api_app import TelegramApiApp
from app.schemas.telegram_account import (
    AuthFlowStatusResponse,
    ConfirmCodeRequest,
    ConfirmCodeResponse,
    ConfirmPasswordRequest,
    ConfirmPasswordResponse,
    SendCodeResponse,
    TgAccountCreate,
    TgAccountResponse,
    TgAccountUpdate,
    VerifyAccountResponse,
)
from app.services.auto_assign import NoAvailableApiAppError, assign_api_app
from app.services.websocket_manager import manager
from app.workers.tg_auth_tasks import (
    unified_auth_task,
    verify_account_task,
)
from app.workers.tg_sync_tasks import parse_single_chat, sync_account_data
from app.workers.tasks import account_health_check
from app.workers.tg_warming_tasks import start_tg_warming

router = APIRouter(prefix="/tg-accounts", tags=["tg-accounts"])
settings = get_settings()
logger = logging.getLogger(__name__)

# Maximum seconds a flow can stay in "init" state before auto-failing.
_FLOW_INIT_TIMEOUT_SECONDS = 60


def _is_admin(user: User) -> bool:
    return bool(user.is_admin)


def _get_account_or_404(
    db: Session, account_id: int, user: User,
) -> TelegramAccount:
    query = db.query(TelegramAccount).filter(TelegramAccount.id == account_id)
    if not _is_admin(user):
        query = query.filter(TelegramAccount.owner_user_id == user.id)
    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")
    return account


_DISPATCH_TIMEOUT_SECONDS = 10


def _safe_dispatch(task, *args) -> None:
    """Dispatch a Celery task with a bounded timeout.

    ``task.delay()`` acquires a connection from the Celery broker pool.
    If the single pool connection is stale or contended, the call can
    block indefinitely.  We run the publish in a daemon thread and
    enforce a hard timeout so the HTTP request always finishes.
    """
    exc_holder: list[BaseException | None] = [None]
    done = threading.Event()

    def _publish() -> None:
        try:
            task.delay(*args)
        except BaseException as e:
            exc_holder[0] = e
        finally:
            done.set()

    t0 = time.monotonic()
    thread = threading.Thread(target=_publish, daemon=True)
    thread.start()

    if not done.wait(timeout=_DISPATCH_TIMEOUT_SECONDS):
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.error(
            "event=task_dispatch_timeout task=%s elapsed_ms=%d",
            task.name, elapsed_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="Task dispatch timed out. Please try again.",
        )

    if exc_holder[0] is not None:
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        logger.error(
            "event=task_dispatch_failed task=%s error=%s elapsed_ms=%d",
            task.name, str(exc_holder[0])[:200], elapsed_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Task queue unavailable. Please try again in a moment.",
        )

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "event=task_dispatched task=%s elapsed_ms=%d",
        task.name, elapsed_ms,
    )


# ─── LIST ────────────────────────────────────────────────────────────

@router.get("", response_model=list[TgAccountResponse])
def list_tg_accounts(
    current_user: User = Depends(require_permission("tg_accounts", "list")),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[TgAccountResponse]:
    query = db.query(TelegramAccount)
    if not _is_admin(current_user):
        query = query.filter(TelegramAccount.owner_user_id == current_user.id)
    accounts = query.order_by(TelegramAccount.created_at.desc()).offset(offset).limit(limit).all()
    return [TgAccountResponse.model_validate(account) for account in accounts]


# ─── GET SINGLE ──────────────────────────────────────────────────────

@router.get("/{account_id}", response_model=TgAccountResponse)
def get_tg_account(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "list")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    account = _get_account_or_404(db, account_id, current_user)
    return TgAccountResponse.model_validate(account)


# ─── DELETE ─────────────────────────────────────────────────────────

@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tg_account(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "delete")),
    db: Session = Depends(get_db),
) -> None:
    account = _get_account_or_404(db, account_id, current_user)

    # Unlink api_app_id to avoid FK constraint violations
    account.api_app_id = None
    account.proxy_id = None
    db.flush()

    # Delete related auth flows
    db.query(TelegramAuthFlow).filter(
        TelegramAuthFlow.account_id == account.id,
    ).delete(synchronize_session="fetch")

    db.delete(account)
    db.commit()
    return None


# ─── UPDATE (manual assign api_app / proxy) ─────────────────────────

@router.patch("/{account_id}", response_model=TgAccountResponse)
def update_tg_account(
    account_id: int,
    payload: TgAccountUpdate,
    current_user: User = Depends(require_permission("tg_accounts", "update")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    account = _get_account_or_404(db, account_id, current_user)

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return TgAccountResponse.model_validate(account)

    # Handle api_app_id="auto" — run auto-assign instead of manual set
    auto_assign_requested = data.get("api_app_id") == "auto"
    if auto_assign_requested:
        data.pop("api_app_id")

    # Apply simple fields first (proxy_id, and api_app_id if it's an int)
    new_api_app_id = data.get("api_app_id", account.api_app_id)
    new_proxy_id = data.get("proxy_id", account.proxy_id)

    # Validate uniqueness: same (api_app_id, proxy_id) on another account
    # is a red flag for Telegram anti-ban (identical api_id + IP).
    # NOTE: The DB constraint UNIQUE(api_app_id, proxy_id) does NOT catch
    # duplicates when proxy_id IS NULL (SQL treats every NULL as distinct),
    # so we must check both the NULL and non-NULL cases at the app level.
    if not auto_assign_requested and new_api_app_id is not None:
        conflict_query = db.query(TelegramAccount).filter(
            TelegramAccount.api_app_id == new_api_app_id,
            TelegramAccount.id != account.id,
        )
        if new_proxy_id is not None:
            conflict_query = conflict_query.filter(
                TelegramAccount.proxy_id == new_proxy_id,
            )
        else:
            conflict_query = conflict_query.filter(
                TelegramAccount.proxy_id.is_(None),
            )
        conflict = conflict_query.first()
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Другой аккаунт (id={conflict.id}) уже использует этот "
                    f"api_app (id={new_api_app_id}) с "
                    f"{'этим прокси (id=' + str(new_proxy_id) + ')' if new_proxy_id else 'отсутствующим прокси'}. "
                    "Два аккаунта с одинаковым api_id и IP — красный флаг для Telegram."
                ),
            )

    # Validate that the manually specified api_app exists
    if "api_app_id" in data and data["api_app_id"] is not None:
        app = db.get(TelegramApiApp, data["api_app_id"])
        if not app:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"API app with id={data['api_app_id']} not found",
            )

    for field, value in data.items():
        setattr(account, field, value)

    # Auto-assign after other fields are applied (proxy_id may affect selection)
    if auto_assign_requested:
        try:
            assign_api_app(account, db)
        except NoAvailableApiAppError as exc:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    db.commit()
    db.refresh(account)
    return TgAccountResponse.model_validate(account)


# ─── ASSIGN RESOURCES (auto-assign api_app) ──────────────────────────

@router.post("/{account_id}/assign-resources", response_model=TgAccountResponse)
def assign_resources(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "assign_resources")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    """Auto-assign the best available API app to the account.

    Uses the least-loaded active app that respects the proxy-uniqueness
    constraint.  Replaces any previously assigned app.
    """
    account = _get_account_or_404(db, account_id, current_user)

    try:
        assign_api_app(account, db)
    except NoAvailableApiAppError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(account)
    return TgAccountResponse.model_validate(account)


# ─── CREATE (register phone) ────────────────────────────────────────

@router.post("", response_model=TgAccountResponse, status_code=status.HTTP_201_CREATED)
def create_tg_account(
    payload: TgAccountCreate,
    current_user: User = Depends(require_permission("tg_accounts", "create")),
    tariff_limits: dict[str, int] = Depends(get_tariff_limits),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    phone = payload.phone

    # Check if this user already has this phone
    existing = (
        db.query(TelegramAccount)
        .filter(
            TelegramAccount.owner_user_id == current_user.id,
            TelegramAccount.phone_e164 == phone,
        )
        .first()
    )
    if existing:
        # Return existing account (idempotent)
        return TgAccountResponse.model_validate(existing)

    # Tariff enforcement
    if not _is_admin(current_user):
        # Lock the user row to prevent concurrent requests from bypassing the limit
        db.query(User).filter(User.id == current_user.id).with_for_update().first()
        max_accounts = tariff_limits["max_accounts"]
        current_count = (
            db.query(TelegramAccount)
            .filter(TelegramAccount.owner_user_id == current_user.id)
            .count()
        )
        if current_count >= max_accounts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account limit reached for your tariff plan",
            )

    account = TelegramAccount(
        owner_user_id=current_user.id,
        phone_e164=phone,
        status=TelegramAccountStatus.new,
        device_config=generate_device_config(),
        last_device_regenerated_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.flush()  # get account.id before auto-assign

    # Auto-assign API app
    try:
        assign_api_app(account, db)
    except NoAvailableApiAppError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    db.commit()
    db.refresh(account)
    return TgAccountResponse.model_validate(account)


# ─── SEND CODE ───────────────────────────────────────────────────────

@router.post("/{account_id}/send-code", response_model=SendCodeResponse)
@limiter.limit("3/minute")
def send_code(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("tg_accounts", "send_code")),
    db: Session = Depends(get_db),
) -> SendCodeResponse:
    account = _get_account_or_404(db, account_id, current_user)

    # Can only send code from these states
    allowed_states = {
        TelegramAccountStatus.new,
        TelegramAccountStatus.code_sent,
        TelegramAccountStatus.error,
        TelegramAccountStatus.disconnected,
    }
    if account.status not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot send code in state '{account.status.value}'. "
            f"Allowed states: {', '.join(s.value for s in allowed_states)}",
        )

    # Expire old flows (including code_submitted from unified_auth flows)
    db.query(TelegramAuthFlow).filter(
        TelegramAuthFlow.account_id == account.id,
        TelegramAuthFlow.state.in_([
            AuthFlowState.init, AuthFlowState.code_sent,
            AuthFlowState.wait_code, AuthFlowState.code_submitted,
            AuthFlowState.wait_password, AuthFlowState.password_submitted,
        ]),
    ).update({"state": AuthFlowState.expired}, synchronize_session="fetch")

    flow = TelegramAuthFlow(
        account_id=account.id,
        phone_e164=account.phone_e164,
        state=AuthFlowState.init,
        expires_at=datetime.now(timezone.utc) + timedelta(seconds=settings.auth_flow_ttl_seconds),
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)

    # Dispatch unified auth task (single connection for send_code + sign_in)
    _safe_dispatch(unified_auth_task, account.id, flow.id)

    return SendCodeResponse(
        flow_id=flow.id,
        status=TgAccountResponse.model_validate(account).status,
        message="Verification code is being sent to your Telegram app",
    )


# ─── AUTH FLOW STATUS (polling endpoint) ──────────────────────────────

@router.get("/{account_id}/auth-flow/{flow_id}", response_model=AuthFlowStatusResponse)
def get_auth_flow_status(
    account_id: int,
    flow_id: str,
    current_user: User = Depends(require_permission("tg_accounts", "list")),
    db: Session = Depends(get_db),
) -> AuthFlowStatusResponse:
    """Poll the status of an auth flow.  Used by the frontend after send-code
    to detect when the Celery task has completed (code_sent / error / etc).
    """
    account = _get_account_or_404(db, account_id, current_user)

    flow = db.get(TelegramAuthFlow, flow_id)
    if not flow or flow.account_id != account.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auth flow not found",
        )

    # Re-read both flow and account to get the latest state
    # (may have been updated by the Celery worker in a separate session)
    db.refresh(flow)
    db.refresh(account)

    # Auto-fail stale flows that stayed in "init" longer than the timeout.
    # This means the worker never picked up the task (crashed, Redis down, etc.).
    if flow.state == AuthFlowState.init and flow.created_at:
        now = datetime.now(timezone.utc)
        created = ensure_utc(flow.created_at)
        age_seconds = (now - created).total_seconds()
        if age_seconds > _FLOW_INIT_TIMEOUT_SECONDS:
            flow.state = AuthFlowState.failed
            flow.last_error = "Timeout waiting for worker to process the request"
            account.status = TelegramAccountStatus.error
            account.last_error = "Verification timed out. Please try again."
            db.commit()
            logger.error(
                "event=flow_init_timeout flow_id=%s account_id=%d age_seconds=%.0f",
                flow.id, account.id, age_seconds,
            )

    return AuthFlowStatusResponse(
        flow_id=flow.id,
        flow_state=flow.state.value if hasattr(flow.state, "value") else str(flow.state),
        account_status=account.status,
        last_error=flow.last_error,
        sent_at=flow.sent_at,
        expires_at=flow.expires_at,
        attempts=flow.attempts,
    )


# ─── CONFIRM CODE ────────────────────────────────────────────────────

@router.post("/{account_id}/confirm-code", response_model=ConfirmCodeResponse)
@limiter.limit("5/minute")
def confirm_code(
    account_id: int,
    payload: ConfirmCodeRequest,
    request: Request,
    current_user: User = Depends(require_permission("tg_accounts", "confirm_code")),
    db: Session = Depends(get_db),
) -> ConfirmCodeResponse:
    account = _get_account_or_404(db, account_id, current_user)

    flow = db.get(TelegramAuthFlow, payload.flow_id)
    if not flow or flow.account_id != account.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auth flow not found",
        )

    allowed_flow_states = (
        AuthFlowState.wait_code,
        AuthFlowState.code_sent,
        AuthFlowState.code_submitted,  # allow re-submit after PhoneCodeInvalid
    )
    if flow.state not in allowed_flow_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Flow is in state '{flow.state.value}', expected 'wait_code'",
        )

    if is_expired(flow.expires_at):
        flow.state = AuthFlowState.expired
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verification flow expired. Please send a new code.",
        )

    if flow.attempts >= settings.auth_flow_max_attempts:
        flow.state = AuthFlowState.failed
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Too many verification attempts. Please start over.",
        )

    meta = flow.meta_json or {}

    # Unified flow: write code to DB for the polling task to pick up.
    new_meta = dict(meta)
    new_meta["submitted_code"] = payload.code
    flow.meta_json = new_meta
    flow.state = AuthFlowState.code_submitted
    db.commit()

    return ConfirmCodeResponse(
        status=TgAccountResponse.model_validate(account).status,
        flow_id=payload.flow_id,
        state="code_submitted",
        next_step="poll",
        message="Code submitted, verifying...",
    )


# ─── CONFIRM PASSWORD (2FA) ─────────────────────────────────────────

@router.post("/{account_id}/confirm-password", response_model=ConfirmPasswordResponse)
@limiter.limit("5/minute")
def confirm_password(
    account_id: int,
    payload: ConfirmPasswordRequest,
    request: Request,
    current_user: User = Depends(require_permission("tg_accounts", "confirm_password")),
    db: Session = Depends(get_db),
) -> ConfirmPasswordResponse:
    account = _get_account_or_404(db, account_id, current_user)

    flow = db.get(TelegramAuthFlow, payload.flow_id)
    if not flow or flow.account_id != account.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Auth flow not found",
        )

    if flow.state != AuthFlowState.wait_password:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Flow is in state '{flow.state.value}', expected 'wait_password'",
        )

    if is_expired(flow.expires_at):
        flow.state = AuthFlowState.expired
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Verification flow expired. Please start over.",
        )

    if flow.attempts >= settings.auth_flow_max_attempts:
        flow.state = AuthFlowState.failed
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Too many attempts. Please start over.",
        )

    # Write password to flow for the running unified_auth_task to pick up
    # (same pattern as confirm-code — no separate Celery task needed).
    meta = flow.meta_json or {}
    flow.meta_json = {**meta, "submitted_password": payload.password}
    flow.state = AuthFlowState.password_submitted
    db.commit()

    return ConfirmPasswordResponse(
        status=TgAccountResponse.model_validate(account).status,
        flow_id=payload.flow_id,
        state="password_submitted",
        next_step="poll",
        message="Password submitted, verifying...",
    )


# ─── VERIFY (session health check, idempotent) ──────────────────────

@router.post("/{account_id}/verify", response_model=VerifyAccountResponse)
@limiter.limit("5/minute")
def verify_tg_account(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("tg_accounts", "verify")),
    db: Session = Depends(get_db),
) -> VerifyAccountResponse:
    """Start or poll a verify job for the account.

    Idempotent: if a verify is already running (lease active), returns the
    current status instead of starting a duplicate task.
    """
    account = _get_account_or_404(db, account_id, current_user)

    # Must have a session to verify
    allowed_states = {
        TelegramAccountStatus.verified,
        TelegramAccountStatus.active,
        TelegramAccountStatus.cooldown,
        TelegramAccountStatus.warming,
        TelegramAccountStatus.error,
    }
    if account.status not in allowed_states:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot verify in state '{account.status.value}'. "
            f"Account must have an active session.",
        )

    # Check if lease is already held (idempotent return)
    if account.verifying:
        from app.core.tz import ensure_utc
        from app.models.telegram_account import VERIFY_LEASE_TTL_SECONDS
        now = datetime.now(timezone.utc)
        started = ensure_utc(account.verifying_started_at) if account.verifying_started_at else None
        if started and (now - started).total_seconds() < VERIFY_LEASE_TTL_SECONDS:
            logger.info(
                "event=verify_already_running account_id=%d task_id=%s",
                account.id, account.verifying_task_id,
            )
            return VerifyAccountResponse(
                account_id=account.id,
                verify_status=account.verify_status or VerifyStatus.running.value,
                verify_reason=account.verify_reason,
                verifying=True,
                message="Verification is already in progress",
                account_status=account.status,
            )

    # Dispatch verify task to Celery worker
    _safe_dispatch(verify_account_task, account.id)

    return VerifyAccountResponse(
        account_id=account.id,
        verify_status=VerifyStatus.pending.value,
        verify_reason=None,
        verifying=False,
        message="Verification task dispatched",
        account_status=account.status,
    )


# ─── DISCONNECT ──────────────────────────────────────────────────────

@router.post("/{account_id}/disconnect", response_model=TgAccountResponse)
def disconnect_tg_account(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "disconnect")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    account = _get_account_or_404(db, account_id, current_user)
    account.status = TelegramAccountStatus.disconnected
    account.session_encrypted = None
    account.last_error = None
    db.commit()
    db.refresh(account)

    manager.broadcast_sync({
        "type": "account_status_changed",
        "user_id": current_user.id,
        "account_id": account.id,
        "status": account.status.value,
    })

    return TgAccountResponse.model_validate(account)


# ─── HEALTH CHECK ────────────────────────────────────────────────────

@router.post("/{account_id}/health-check", response_model=TgAccountResponse)
@limiter.limit("5/minute")
def tg_health_check(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("tg_accounts", "health_check")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    account = _get_account_or_404(db, account_id, current_user)
    if account.status not in (
        TelegramAccountStatus.verified,
        TelegramAccountStatus.active,
        TelegramAccountStatus.cooldown,
        TelegramAccountStatus.warming,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account must be verified/active to run health check",
        )

    _safe_dispatch(account_health_check, account.id)

    return TgAccountResponse.model_validate(account)


# ─── WARMUP ──────────────────────────────────────────────────────────

@router.post("/{account_id}/warmup", response_model=TgAccountResponse)
@limiter.limit("5/minute")
def tg_warmup(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("tg_accounts", "warmup")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    account = _get_account_or_404(db, account_id, current_user)
    if account.status not in (
        TelegramAccountStatus.verified,
        TelegramAccountStatus.active,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Account must be verified/active to start warmup",
        )

    now = datetime.now(timezone.utc)
    rest_hours = random.uniform(
        settings.warming_rest_hours_min,
        settings.warming_rest_hours_max,
    )
    rest_until = now + timedelta(hours=rest_hours)

    account.status = TelegramAccountStatus.warming
    account.warming_started_at = now
    account.warming_day = 0
    account.warming_actions_completed = 0
    account.warming_joined_channels = {
        "rest_until": rest_until.isoformat(),
        "channels": [],
        "done_once": [],
    }
    account.cooldown_until = None
    account.flood_wait_at = None
    account.last_error = None
    db.commit()
    db.refresh(account)

    manager.broadcast_sync({
        "type": "account_status_changed",
        "user_id": current_user.id,
        "account_id": account.id,
        "status": account.status.value,
        "warming_day": account.warming_day,
        "actions_completed": account.warming_actions_completed,
        "target_actions": account.target_warming_actions,
    })

    # Do NOT dispatch start_tg_warming immediately —
    # resume_tg_warming will pick it up after the rest period.

    return TgAccountResponse.model_validate(account)


# ─── ACTIVATE (skip warmup) ───────────────────────────────────────────

@router.post("/{account_id}/activate")
def activate_account(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "update")),
    db: Session = Depends(get_db),
) -> dict:
    """Переводит аккаунт в статус active (для вручную прогретых аккаунтов)."""
    account = _get_account_or_404(db, account_id, current_user)

    if account.status not in (TelegramAccountStatus.verified, TelegramAccountStatus.cooldown):
        raise HTTPException(400, f"Cannot activate account in status {account.status.value}")

    if not account.session_encrypted:
        raise HTTPException(400, "Account has no session. Please re-authorize first.")

    account.status = TelegramAccountStatus.active
    account.last_error = None
    db.commit()

    manager.broadcast_sync({
        "type": "account_status_changed",
        "user_id": current_user.id,
        "account_id": account.id,
        "status": account.status.value,
    })

    return {"status": "active", "message": "Account activated"}


# ─── REGENERATE DEVICE ───────────────────────────────────────────────

@router.post("/{account_id}/regenerate-device", response_model=TgAccountResponse)
def tg_regenerate_device(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "regenerate_device")),
    db: Session = Depends(get_db),
) -> TgAccountResponse:
    account = _get_account_or_404(db, account_id, current_user)
    account.device_config = generate_device_config()
    account.last_device_regenerated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)
    return TgAccountResponse.model_validate(account)


# ─── SYNC (manual trigger) ───────────────────────────────────────────

@router.post("/{account_id}/sync")
def trigger_sync(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "update")),
    db: Session = Depends(get_db),
) -> dict:
    """Manually trigger full account sync (dialogs + members)."""
    account = _get_account_or_404(db, account_id, current_user)

    if account.status not in (
        TelegramAccountStatus.verified,
        TelegramAccountStatus.active,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot sync in state '{account.status.value}'. "
            "Account must be verified or active.",
        )

    _safe_dispatch(sync_account_data, account.id)

    return {"status": "sync_started"}


# ─── PARSE SINGLE CHAT ──────────────────────────────────────────────

@router.post("/{account_id}/chats/{chat_id}/parse")
def trigger_parse_single_chat(
    account_id: int,
    chat_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "update")),
    db: Session = Depends(get_db),
) -> dict:
    """Trigger parsing of members for a single chat."""
    account = _get_account_or_404(db, account_id, current_user)

    account_chat = (
        db.query(TgAccountChat)
        .filter(
            TgAccountChat.account_id == account.id,
            or_(
                TgAccountChat.id == chat_id,
                TgAccountChat.chat_id == chat_id,
            ),
        )
        .first()
    )
    if not account_chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found for this account",
        )

    _safe_dispatch(parse_single_chat, account.id, account_chat.chat_id)

    return {"status": "parsing_started", "chat_id": account_chat.chat_id}


# ─── ACCOUNT CHATS ───────────────────────────────────────────────────

@router.get("/{account_id}/chats")
def list_account_chats(
    account_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "list")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """List chats associated with the account."""
    account = _get_account_or_404(db, account_id, current_user)

    chats = (
        db.query(TgAccountChat)
        .filter(TgAccountChat.account_id == account.id)
        .order_by(TgAccountChat.members_count.desc())
        .all()
    )

    return [
        {
            "id": c.id,
            "chat_id": c.chat_id,
            "title": c.title,
            "username": c.username,
            "chat_type": c.chat_type,
            "members_count": c.members_count,
            "is_creator": c.is_creator,
            "is_admin": c.is_admin,
            "last_parsed_at": c.last_parsed_at.isoformat() if c.last_parsed_at else None,
            "first_seen_at": c.first_seen_at.isoformat() if c.first_seen_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in chats
    ]


# ─── CHAT MEMBERS ────────────────────────────────────────────────────

@router.get("/{account_id}/chats/{chat_id}/members")
def list_chat_members(
    account_id: int,
    chat_id: int,
    current_user: User = Depends(require_permission("tg_accounts", "list")),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="last_online_at"),
) -> list[dict]:
    """List parsed members of a specific chat."""
    account = _get_account_or_404(db, account_id, current_user)

    # Verify the chat belongs to this account
    account_chat = (
        db.query(TgAccountChat)
        .filter(
            TgAccountChat.account_id == account.id,
            or_(
                TgAccountChat.id == chat_id,
                TgAccountChat.chat_id == chat_id,
            ),
        )
        .first()
    )
    if not account_chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat not found for this account",
        )

    # Determine sort column
    sort_column_map = {
        "last_online_at": TgUser.last_online_at,
        "username": TgUser.username,
        "first_name": TgUser.first_name,
        "first_seen_at": TgChatMember.first_seen_at,
    }
    sort_col = sort_column_map.get(sort_by, TgUser.last_online_at)

    members = (
        db.query(TgUser, TgChatMember)
        .join(TgChatMember, TgChatMember.user_id == TgUser.id)
        .filter(TgChatMember.chat_id == account_chat.chat_id)
        .order_by(sort_col.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "user_id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "is_premium": user.is_premium,
            "last_online_at": user.last_online_at.isoformat() if user.last_online_at else None,
            "role": member.role.value if hasattr(member.role, "value") else str(member.role),
            "joined_at": member.joined_at.isoformat() if member.joined_at else None,
        }
        for user, member in members
    ]


# ─── DIALOGS (live from Telegram) ────────────────────────────────────


@router.get("/{account_id}/dialogs")
async def get_account_dialogs(
    account_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: User = Depends(require_permission("tg_accounts", "read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Загружает ВСЕ диалоги аккаунта напрямую из Telegram API.
    Включает личные чаты, группы, каналы, ботов."""
    account = _get_account_or_404(db, account_id, current_user)

    if account.status not in (TelegramAccountStatus.active, TelegramAccountStatus.verified):
        raise HTTPException(400, "Account must be active or verified")
    if not account.session_encrypted:
        raise HTTPException(400, "No session")

    proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
    client = create_tg_account_client(account, proxy)

    try:
        await asyncio.wait_for(client.connect(), timeout=15)

        dialogs: list[dict] = []
        async for dialog in client.get_dialogs(limit=limit):
            chat = dialog.chat
            dialogs.append({
                "chat_id": chat.id,
                "title": chat.title or chat.first_name or "Unknown",
                "username": getattr(chat, "username", None),
                "type": chat.type.value,
                "unread_count": dialog.unread_messages_count,
                "last_message": {
                    "text": (dialog.top_message.text or dialog.top_message.caption or "")[:200] if dialog.top_message else None,
                    "date": dialog.top_message.date.isoformat() if dialog.top_message and dialog.top_message.date else None,
                    "from": dialog.top_message.from_user.first_name if dialog.top_message and dialog.top_message.from_user else None,
                } if dialog.top_message else None,
                "members_count": getattr(chat, "members_count", None),
            })

        return dialogs
    except (AuthKeyUnregistered, SessionRevoked) as exc:
        account.status = TelegramAccountStatus.error
        account.session_encrypted = None
        account.last_error = f"Session invalid: {type(exc).__name__}"
        db.commit()
        raise HTTPException(401, "Telegram session expired. Please re-authorize account.")
    except UserDeactivatedBan:
        account.status = TelegramAccountStatus.banned
        account.last_error = "Account banned by Telegram"
        db.commit()
        raise HTTPException(403, "Account banned by Telegram")
    except asyncio.TimeoutError:
        raise HTTPException(504, "Telegram connection timeout")
    except Exception as exc:
        raise HTTPException(502, f"Telegram error: {str(exc)[:200]}")
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=10)
        except Exception:
            pass


# ─── CHAT MESSAGES (live from Telegram) ──────────────────────────────


@router.get("/{account_id}/dialogs/{chat_id}/messages")
async def get_chat_messages(
    account_id: int,
    chat_id: int,
    limit: int = Query(default=50, ge=1, le=200),
    offset_id: int = Query(default=0),
    current_user: User = Depends(require_permission("tg_accounts", "read")),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Читает последние сообщения из чата."""
    account = _get_account_or_404(db, account_id, current_user)

    if account.status not in (TelegramAccountStatus.active, TelegramAccountStatus.verified):
        raise HTTPException(400, "Account must be active or verified")
    if not account.session_encrypted:
        raise HTTPException(400, "No session")

    proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
    client = create_tg_account_client(account, proxy)

    try:
        await asyncio.wait_for(client.connect(), timeout=15)

        messages: list[dict] = []
        async for msg in client.get_chat_history(chat_id, limit=limit, offset_id=offset_id):
            messages.append({
                "id": msg.id,
                "text": msg.text or msg.caption or "",
                "date": msg.date.isoformat() if msg.date else None,
                "from_user": {
                    "id": msg.from_user.id,
                    "name": msg.from_user.first_name or "",
                    "username": msg.from_user.username,
                } if msg.from_user else None,
                "media_type": msg.media.value if msg.media else None,
                "reply_to_message_id": msg.reply_to_message_id,
            })

        return messages
    except (AuthKeyUnregistered, SessionRevoked) as exc:
        account.status = TelegramAccountStatus.error
        account.session_encrypted = None
        account.last_error = f"Session invalid: {type(exc).__name__}"
        db.commit()
        raise HTTPException(401, "Telegram session expired. Please re-authorize account.")
    except UserDeactivatedBan:
        account.status = TelegramAccountStatus.banned
        account.last_error = "Account banned by Telegram"
        db.commit()
        raise HTTPException(403, "Account banned by Telegram")
    except asyncio.TimeoutError:
        raise HTTPException(504, "Telegram connection timeout")
    except Exception as exc:
        raise HTTPException(502, f"Telegram error: {str(exc)[:200]}")
    finally:
        try:
            await asyncio.wait_for(client.disconnect(), timeout=10)
        except Exception:
            pass
