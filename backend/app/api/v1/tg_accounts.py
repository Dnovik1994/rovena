"""API router for Telegram account management via phone + OTP flow.

All endpoints use synchronous ``def`` so FastAPI runs them in a threadpool,
keeping the async event loop free for WebSocket / background tasks.
"""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.core.tz import ensure_utc, is_expired

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_tariff_limits
from app.clients.device_generator import generate_device_config
from app.core.database import get_db
from app.core.rbac import require_permission
from app.core.rate_limit import limiter
from app.core.settings import get_settings
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
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
from app.workers.tg_auth_tasks import confirm_code_task, confirm_password_task, send_code_task, verify_account_task
from app.workers.tasks import account_health_check, start_warming

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

    # Expire old flows
    db.query(TelegramAuthFlow).filter(
        TelegramAuthFlow.account_id == account.id,
        TelegramAuthFlow.state.in_([
            AuthFlowState.init, AuthFlowState.code_sent,
            AuthFlowState.wait_code, AuthFlowState.wait_password,
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

    # Dispatch to worker — fail fast if Redis is down
    _safe_dispatch(send_code_task, account.id, flow.id)

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

    if flow.state not in (AuthFlowState.wait_code, AuthFlowState.code_sent):
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

    # Dispatch to worker — fail fast if Redis is down
    _safe_dispatch(confirm_code_task, account.id, flow.id, payload.code)

    return ConfirmCodeResponse(
        status=TgAccountResponse.model_validate(account).status,
        flow_id=payload.flow_id,
        state="processing",
        next_step="poll",
        message="Verifying code...",
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

    # Dispatch to worker — fail fast if Redis is down
    _safe_dispatch(confirm_password_task, account.id, flow.id, payload.password)

    return ConfirmPasswordResponse(
        status=TgAccountResponse.model_validate(account).status,
        flow_id=payload.flow_id,
        state="processing",
        next_step="poll",
        message="Verifying 2FA password...",
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

    account.status = TelegramAccountStatus.warming
    account.warming_started_at = datetime.now(timezone.utc)
    account.warming_actions_completed = 0
    account.cooldown_until = None
    db.commit()
    db.refresh(account)

    manager.broadcast_sync({
        "type": "account_status_changed",
        "user_id": current_user.id,
        "account_id": account.id,
        "status": account.status.value,
        "actions_completed": account.warming_actions_completed,
        "target_actions": account.target_warming_actions,
    })

    _safe_dispatch(start_warming, account.id)

    return TgAccountResponse.model_validate(account)


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
