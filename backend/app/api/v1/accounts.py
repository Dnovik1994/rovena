from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.rbac import require_permission
from app.core.database import get_db
from app.api.deps import get_tariff_limits
from app.clients.device_generator import generate_device_config
from app.models.account import Account, AccountStatus
from app.models.user import User
from app.core.rate_limit import limiter
from app.schemas.account import AccountCreate, AccountResponse, AccountUpdate, AccountVerifyResponse
from app.services.websocket_manager import manager
from app.workers.tasks import account_health_check, start_warming
from pyrogram.errors import SessionPasswordNeeded
from app.clients.telegram_client import get_client
from app.models.proxy import Proxy

router = APIRouter(tags=["accounts"])


def _is_admin(user: User) -> bool:
    return bool(user.is_admin)


@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(
    current_user: User = Depends(require_permission("accounts", "list")),
    db: Session = Depends(get_db),
) -> list[AccountResponse]:
    query = db.query(Account)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)
    accounts = query.order_by(Account.created_at.desc()).all()
    return [AccountResponse.model_validate(account) for account in accounts]


@router.post("/accounts", response_model=AccountResponse, status_code=status.HTTP_201_CREATED)
async def create_account(
    payload: AccountCreate,
    current_user: User = Depends(require_permission("accounts", "create")),
    tariff_limits: dict[str, int] = Depends(get_tariff_limits),
    db: Session = Depends(get_db),
) -> AccountResponse:
    if not _is_admin(current_user) and payload.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    # Enforce tariff account limit at creation time (not just at campaign start)
    if not _is_admin(current_user):
        max_accounts = tariff_limits["max_accounts"]
        current_count = db.query(Account).filter(Account.owner_id == current_user.id).count()
        if current_count >= max_accounts:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Account limit reached for your tariff plan",
            )

    device_config = payload.device_config or generate_device_config()

    account = Account(
        user_id=payload.user_id,
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
async def update_account(
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
async def delete_account(
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
async def start_account_warming(
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


@router.post("/accounts/{account_id}/verify", response_model=AccountVerifyResponse)
@limiter.limit("5/minute")
async def verify_account(
    account_id: int,
    request: Request,
    current_user: User = Depends(require_permission("accounts", "verify")),
    db: Session = Depends(get_db),
) -> AccountVerifyResponse:
    query = db.query(Account).filter(Account.id == account_id)
    if not _is_admin(current_user):
        query = query.filter(Account.owner_id == current_user.id)

    account = query.first()
    if not account:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
    client = get_client(account, proxy)
    try:
        async with client:
            me = await client.get_me()
    except SessionPasswordNeeded:
        return AccountVerifyResponse(needs_password=True, account=None)

    account.telegram_id = me.id
    account.username = me.username
    account.first_name = me.first_name
    account.status = AccountStatus.verified
    account.last_activity_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(account)

    manager.broadcast_sync(
        {
            "type": "account_update",
            "user_id": current_user.id,
            "account_id": account.id,
            "status": account.status,
        }
    )

    return AccountVerifyResponse(needs_password=False, account=AccountResponse.model_validate(account))


@router.post("/accounts/{account_id}/regenerate-device", response_model=AccountResponse)
async def regenerate_device_config(
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
