from fastapi import APIRouter, Depends, HTTPException, Query, status
import stripe
from pydantic import BaseModel
from sqlalchemy import or_, cast, String
from sqlalchemy.orm import Session

from app.api.deps import get_current_admin
from app.core.cache import delete, get_json, set_json
from app.core.database import get_db
from app.core.settings import get_settings
from app.models.account import Account, AccountStatus
from app.models.campaign import Campaign, CampaignStatus
from app.models.proxy import Proxy, ProxyStatus
from app.models.tariff import Tariff
from app.models.user import User, UserRole
from app.schemas.tariff import TariffCreate, TariffResponse, TariffUpdate, UserTariffUpdate

router = APIRouter(tags=["admin"])
settings = get_settings()

TARIFFS_CACHE_KEY = "tariffs:all"


class AdminUserUpdate(BaseModel):
    is_active: bool | None = None
    role: str | None = None


class AdminCheckoutRequest(BaseModel):
    tariff_id: int
    user_id: int | None = None


@router.get("/stats")
async def admin_stats(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, int]:
    users = db.query(User).count()
    accounts = db.query(Account).count()
    accounts_active = db.query(Account).filter(Account.status == AccountStatus.active).count()
    accounts_warming = db.query(Account).filter(Account.status == AccountStatus.warming).count()
    proxies = db.query(Proxy).count()
    proxies_online = db.query(Proxy).filter(Proxy.status == ProxyStatus.active).count()
    campaigns = db.query(Campaign).count()
    campaigns_active = (
        db.query(Campaign).filter(Campaign.status == CampaignStatus.active).count()
    )
    return {
        "users": users,
        "accounts": accounts,
        "accounts_active": accounts_active,
        "accounts_warming": accounts_warming,
        "proxies": proxies,
        "proxies_online": proxies_online,
        "campaigns": campaigns,
        "campaigns_active": campaigns_active,
    }


@router.get("/users")
async def admin_users(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
    search: str | None = None,
    tariff: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    query = db.query(User, Tariff).outerjoin(Tariff, User.tariff_id == Tariff.id)
    if search:
        query = query.filter(
            or_(
                User.username.ilike(f"%{search}%"),
                cast(User.telegram_id, String).ilike(f"%{search}%"),
            )
        )
    if tariff:
        query = query.filter(Tariff.name == tariff)
    users = query.order_by(User.id.asc()).offset(offset).limit(limit).all()
    items = [
        {
            "id": user.id,
            "telegram_id": user.telegram_id,
            "username": user.username,
            "is_admin": user.is_admin,
            "is_active": user.is_active,
            "role": user.role.value if user.role else None,
            "tariff": (
                {
                    "id": tariff_row.id,
                    "name": tariff_row.name,
                    "max_accounts": tariff_row.max_accounts,
                    "max_invites_day": tariff_row.max_invites_day,
                    "price": tariff_row.price,
                }
                if tariff_row
                else None
            ),
        }
        for user, tariff_row in users
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/users/{user_id}")
async def admin_user_detail(
    user_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "role": user.role.value if user.role else None,
        "tariff": (
            {
                "id": user.tariff.id,
                "name": user.tariff.name,
                "max_accounts": user.tariff.max_accounts,
                "max_invites_day": user.tariff.max_invites_day,
                "price": user.tariff.price,
            }
            if user.tariff
            else None
        ),
    }


@router.patch("/users/{user_id}")
async def admin_user_update(
    user_id: int,
    payload: AdminUserUpdate,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.role is not None:
        try:
            user.role = UserRole(payload.role)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role"
            ) from exc
    db.commit()
    db.refresh(user)
    await delete(f"user:{user.id}")
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "role": user.role.value if user.role else None,
        "tariff": (
            {
                "id": user.tariff.id,
                "name": user.tariff.name,
                "max_accounts": user.tariff.max_accounts,
                "max_invites_day": user.tariff.max_invites_day,
                "price": user.tariff.price,
            }
            if user.tariff
            else None
        ),
    }


@router.patch("/users/{user_id}/tariff")
async def admin_user_tariff_update(
    user_id: int,
    payload: UserTariffUpdate,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TariffResponse:
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    tariff = db.get(Tariff, payload.tariff_id)
    if not tariff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tariff not found")

    user.tariff_id = tariff.id
    db.commit()
    db.refresh(user)
    await delete(f"user:{user.id}")
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "role": user.role.value if user.role else None,
        "tariff": (
            {
                "id": tariff.id,
                "name": tariff.name,
                "max_accounts": tariff.max_accounts,
                "max_invites_day": tariff.max_invites_day,
                "price": tariff.price,
            }
            if tariff
            else None
        ),
    }


@router.get("/tariffs", response_model=list[TariffResponse])
async def admin_tariffs(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> list[TariffResponse]:
    cached = await get_json(TARIFFS_CACHE_KEY)
    if cached:
        return [TariffResponse(**item) for item in cached.get("items", [])]
    tariffs = db.query(Tariff).order_by(Tariff.id.asc()).all()
    payload = [TariffResponse.model_validate(tariff).model_dump() for tariff in tariffs]
    await set_json(TARIFFS_CACHE_KEY, {"items": payload}, ttl_seconds=60)
    return [TariffResponse(**item) for item in payload]


@router.post(
    "/tariffs",
    response_model=TariffResponse,
    status_code=status.HTTP_201_CREATED,
)
async def admin_tariff_create(
    payload: TariffCreate,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TariffResponse:
    existing = db.query(Tariff).filter(Tariff.name == payload.name).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tariff exists")

    tariff = Tariff(
        name=payload.name,
        max_accounts=payload.max_accounts,
        max_invites_day=payload.max_invites_day,
        price=payload.price,
    )
    db.add(tariff)
    db.commit()
    db.refresh(tariff)
    await delete(TARIFFS_CACHE_KEY)
    await delete(f"tariff_limits:{tariff.id}")
    return TariffResponse.model_validate(tariff)


@router.patch("/tariffs/{tariff_id}", response_model=TariffResponse)
async def admin_tariff_update(
    tariff_id: int,
    payload: TariffUpdate,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> TariffResponse:
    tariff = db.get(Tariff, tariff_id)
    if not tariff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tariff not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(tariff, field, value)
    db.commit()
    db.refresh(tariff)
    await delete(TARIFFS_CACHE_KEY)
    await delete(f"tariff:{tariff.id}")
    await delete(f"tariff_limits:{tariff.id}")
    return TariffResponse.model_validate(tariff)


@router.delete("/tariffs/{tariff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_tariff_delete(
    tariff_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> None:
    tariff = db.get(Tariff, tariff_id)
    if not tariff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tariff not found")

    assigned_count = db.query(User).filter(User.tariff_id == tariff.id).count()
    if assigned_count > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tariff assigned to users",
        )

    db.delete(tariff)
    db.commit()
    await delete(TARIFFS_CACHE_KEY)
    await delete(f"tariff:{tariff.id}")
    await delete(f"tariff_limits:{tariff.id}")
    return None


@router.post("/subscriptions/create-checkout")
async def admin_create_checkout(
    payload: AdminCheckoutRequest,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, str]:
    if not settings.stripe_secret_key:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Stripe is not configured",
        )

    tariff = db.get(Tariff, payload.tariff_id)
    if not tariff:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tariff not found")

    if tariff.price is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tariff price is required for checkout",
        )

    user = current_user
    if payload.user_id:
        user = db.get(User, payload.user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    stripe.api_key = settings.stripe_secret_key
    session = stripe.checkout.Session.create(
        mode="payment",
        payment_method_types=["card"],
        line_items=[
            {
                "price_data": {
                    "currency": "usd",
                    "product_data": {"name": tariff.name},
                    "unit_amount": int(tariff.price * 100),
                },
                "quantity": 1,
            }
        ],
        success_url=f"{settings.web_base_url}/subscription?status=success",
        cancel_url=f"{settings.web_base_url}/subscription?status=cancel",
        metadata={"user_id": str(user.id), "tariff_id": str(tariff.id)},
    )
    return {"checkout_url": session.url}


@router.get("/proxies")
async def admin_proxies(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    proxies = db.query(Proxy).order_by(Proxy.id.asc()).offset(offset).limit(limit).all()
    items = [
        {
            "id": proxy.id,
            "host": proxy.host,
            "port": proxy.port,
            "type": proxy.type.value if proxy.type else None,
            "status": proxy.status.value if proxy.status else None,
            "country": proxy.country,
            "last_check": proxy.last_check,
            "latency_ms": proxy.latency_ms,
        }
        for proxy in proxies
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/proxies/{proxy_id}")
async def admin_proxy_detail(
    proxy_id: int,
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    proxy = db.get(Proxy, proxy_id)
    if not proxy:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proxy not found")
    return {
        "id": proxy.id,
        "host": proxy.host,
        "port": proxy.port,
        "type": proxy.type.value if proxy.type else None,
        "status": proxy.status.value if proxy.status else None,
        "country": proxy.country,
        "last_check": proxy.last_check,
        "latency_ms": proxy.latency_ms,
    }


@router.post("/proxies/validate")
async def admin_proxy_validate(
    current_user: User = Depends(get_current_admin),
) -> dict[str, bool]:
    return {"valid": True}


@router.get("/accounts")
async def admin_accounts(
    current_user: User = Depends(get_current_admin),
    db: Session = Depends(get_db),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, object]:
    accounts = (
        db.query(Account, Proxy)
        .outerjoin(Proxy, Proxy.id == Account.proxy_id)
        .order_by(Account.id.asc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    items = [
        {
            "id": account.id,
            "telegram_id": account.telegram_id,
            "status": account.status.value if account.status else None,
            "owner_id": account.owner_id,
            "user_id": account.user_id,
            "proxy": (
                {
                    "id": proxy.id,
                    "host": proxy.host,
                    "port": proxy.port,
                    "status": proxy.status.value if proxy.status else None,
                }
                if proxy
                else None
            ),
            "warming_actions_completed": account.warming_actions_completed,
            "target_warming_actions": account.target_warming_actions,
        }
        for account, proxy in accounts
    ]
    return {"items": items, "limit": limit, "offset": offset}
