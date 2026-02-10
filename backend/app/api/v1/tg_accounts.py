"""API router for Telegram account management via phone + OTP flow."""

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_tariff_limits
from app.clients.device_generator import generate_device_config
from app.core.database import get_db
from app.core.rbac import require_permission
from app.core.rate_limit import limiter
from app.core.settings import get_settings
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import AuthFlowState, TelegramAuthFlow
from app.models.user import User
from app.schemas.telegram_account import (
    AuthFlowStatusResponse,
    ConfirmCodeRequest,
    ConfirmCodeResponse,
    ConfirmPasswordRequest,
    ConfirmPasswordResponse,
    SendCodeResponse,
    TgAccountCreate,
    TgAccountResponse,
)
from app.services.websocket_manager import manager
from app.workers.tg_auth_tasks import confirm_code_task, confirm_password_task, send_code_task
from app.workers.tasks import account_health_check, start_warming

router = APIRouter(prefix="/tg-accounts", tags=["tg-accounts"])
settings = get_settings()


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

    # Dispatch to worker
    send_code_task.delay(account.id, flow.id)

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

    if flow.expires_at and flow.expires_at < datetime.now(timezone.utc):
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

    # Dispatch to worker
    confirm_code_task.delay(account.id, flow.id, payload.code)

    return ConfirmCodeResponse(
        status=TgAccountResponse.model_validate(account).status,
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

    if flow.attempts >= settings.auth_flow_max_attempts:
        flow.state = AuthFlowState.failed
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Too many attempts. Please start over.",
        )

    confirm_password_task.delay(account.id, flow.id, payload.password)

    return ConfirmPasswordResponse(
        status=TgAccountResponse.model_validate(account).status,
        message="Verifying 2FA password...",
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

    # Reuse existing health check task via legacy Account compatibility
    # The task just needs .id, .proxy_id, .device_config, .status, .owner_id
    account_health_check.delay(account.id)

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

    start_warming.delay(account.id)

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
