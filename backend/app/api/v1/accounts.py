import logging
import threading
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.core.rbac import require_permission
from app.core.database import get_db
from app.api.deps import get_tariff_limits
from app.clients.device_generator import generate_device_config
from app.core.metrics import verify_account_duration_seconds
from app.models.account import Account, AccountStatus
from app.models.user import User
from app.core.rate_limit import limiter
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate, AccountVerifyResponse
from app.services.websocket_manager import manager
from app.workers.tasks import account_health_check, start_warming, legacy_verify_account
from app.clients.telegram_client import TelegramClientDisabledError, get_client
from app.models.proxy import Proxy

logger = logging.getLogger(__name__)

router = APIRouter(tags=["accounts"])


def _is_admin(user: User) -> bool:
    return bool(user.is_admin)


@router.get("/accounts", response_model=list[AccountResponse])
def list_accounts(
    current_user: User = Depends(require_permission("accounts", "list")),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[AccountResponse]:
    query = db.query(Account)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)
    accounts = query.order_by(Account.created_at.desc()).offset(offset).limit(limit).all()
    return [AccountResponse.model_validate(account) for account in accounts]


def _resolve_user_id(db: Session, value: int) -> User | None:
    """Resolve a value that could be users.id or users.telegram_id to a User."""
    user = db.get(User, value)
    if user:
        return user
    return db.query(User).filter(User.telegram_id == value).first()


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: AccountCreate,
    current_user: User = Depends(require_permission("accounts", "create")),
    tariff_limits: dict[str, int] = Depends(get_tariff_limits),
    db: Session = Depends(get_db),
) -> AccountResponse:
    # Resolve user_id: default to current user; if provided, validate it exists
    if payload.user_id is None:
        resolved_user_id = current_user.id
    else:
        resolved_user = _resolve_user_id(db, payload.user_id)
        if not resolved_user:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"User not found for user_id={payload.user_id}. "
                "Provide a valid internal user ID.",
            )
        resolved_user_id = resolved_user.id

    if not _is_admin(current_user) and resolved_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Enforce tariff account limit at creation time (not just at campaign start)
    if not _is_admin(current_user):
        # Lock the user row to prevent concurrent requests from bypassing the limit
        db.query(User).filter(User.id == current_user.id).with_for_update().first()
        max_accounts = tariff_limits["max_accounts"]
        current_count = db.query(Account).filter(Account.owner_id == current_user.id).count()
        if current_count >= max_accounts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account limit reached for your tariff plan",
            )

    device_config = payload.device_config or generate_device_config()

    account = Account(
        user_id=resolved_user_id,
        owner_id=current_user.id,
        telegram_id=payload.telegram_id,
        phone=payload.phone,
        username=payload.username,
        first_name=payload.first_name,
        status=payload.status or AccountStatus.new,
        proxy_id=payload.proxy_id,
        device_config=device_config,
        last_device_regenerated_at=datetime.now(timezone.utc),
    )
    db.add(account)
    db.commit()
    db.refresh(account)

    account_health_check.delay(account.id)

    return AccountResponse.model_validate(account)


@router.patch("/accounts/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: int,
    payload: AccountUpdate,
    current_user: User = Depends(require_permission("accounts", "update")),
    db: Session = Depends(get_db),
) -> AccountResponse:
    query = db.query(Account).filter(Account.id == account_id)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    _ACCOUNT_UPDATE_FIELDS = {
        "phone", "username", "first_name", "status", "proxy_id",
        "device_config", "warming_started_at", "last_activity_at",
        "warming_actions_completed", "target_warming_actions",
        "cooldown_until", "last_device_regenerated_at",
    }
    for field, value in payload.model_dump(exclude_unset=True).items():
        if field not in _ACCOUNT_UPDATE_FIELDS:
            continue
        setattr(account, field, value)

    db.commit()
    db.refresh(account)
    return AccountResponse.model_validate(account)


@router.delete("/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    account_id: int,
    current_user: User = Depends(require_permission("accounts", "delete")),
    db: Session = Depends(get_db),
) -> None:
    query = db.query(Account).filter(Account.id == account_id)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    db.delete(account)
    db.commit()
    return None


@router.post("/accounts/{account_id}/start-warming", response_model=AccountResponse)
@limiter.limit("5/minute")
def start_account_warming(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("accounts", "start_warming")),
    db: Session = Depends(get_db),
) -> AccountResponse:
    query = db.query(Account).filter(Account.id == account_id)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    account.status = AccountStatus.warming
    account.warming_started_at = datetime.now(timezone.utc)
    account.warming_actions_completed = 0
    account.cooldown_until = None
    db.commit()
    db.refresh(account)

    manager.broadcast_sync(
        {
            "type": "account_update",
            "user_id": current_user.id,
            "account_id": account.id,
            "status": account.status,
            "actions_completed": account.warming_actions_completed,
            "target_actions": account.target_warming_actions,
            "cooldown_until": None,
        }
    )

    start_warming.delay(account.id)

    return AccountResponse.model_validate(account)


_DISPATCH_TIMEOUT_SECONDS = 10


def _safe_dispatch(task, *args) -> None:
    """Dispatch a Celery task with a bounded timeout."""
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
        logger.error("event=task_dispatch_timeout task=%s elapsed_ms=%d", task.name, elapsed_ms)
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


@router.post("/accounts/{account_id}/verify", response_model=AccountVerifyResponse)
@limiter.limit("5/minute")
def verify_account(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("accounts", "verify")),
    db: Session = Depends(get_db),
) -> AccountVerifyResponse:
    """Non-blocking verify: dispatches to Celery worker, returns immediately."""
    query = db.query(Account).filter(Account.id == account_id)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    _safe_dispatch(legacy_verify_account, account.id)

    logger.info(
        "event=verify_account_dispatched account_id=%d user_id=%d",
        account_id, current_user.id,
    )

    return AccountVerifyResponse(needs_password=False, account=AccountResponse.model_validate(account))


@router.post("/accounts/{account_id}/regenerate-device", response_model=AccountResponse)
def regenerate_device_config(
    account_id: int,
    current_user: User = Depends(require_permission("accounts", "update")),
    db: Session = Depends(get_db),
) -> AccountResponse:
    query = db.query(Account).filter(Account.id == account_id)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    account.device_config = generate_device_config()
    account.last_device_regenerated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)

    return AccountResponse.model_validate(account)
