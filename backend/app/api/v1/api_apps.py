from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rbac import require_permission
from app.models.telegram_account import TelegramAccount
from app.models.telegram_api_app import TelegramApiApp
from app.schemas.telegram_api_app import (
    ApiAppCreate,
    ApiAppCreateResponse,
    ApiAppHashReveal,
    ApiAppListResponse,
    ApiAppResponse,
    ApiAppUpdate,
)

router = APIRouter(tags=["api-apps"])


@router.get("/api-apps", response_model=list[ApiAppListResponse])
def list_api_apps(
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("api_apps", "list")),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[ApiAppListResponse]:
    counts_subq = (
        db.query(
            TelegramAccount.api_app_id,
            func.count(TelegramAccount.id).label("cnt"),
        )
        .group_by(TelegramAccount.api_app_id)
        .subquery()
    )

    rows = (
        db.query(TelegramApiApp, func.coalesce(counts_subq.c.cnt, 0).label("current_accounts_count"))
        .outerjoin(counts_subq, TelegramApiApp.id == counts_subq.c.api_app_id)
        .order_by(TelegramApiApp.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    result = []
    for app, count in rows:
        data = ApiAppResponse.model_validate(app).model_dump()
        data["current_accounts_count"] = count
        result.append(ApiAppListResponse(**data))
    return result


@router.post("/api-apps", response_model=ApiAppCreateResponse, status_code=status.HTTP_201_CREATED)
def create_api_app(
    payload: ApiAppCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("api_apps", "create")),
) -> ApiAppCreateResponse:
    existing = db.query(TelegramApiApp).filter(TelegramApiApp.api_id == payload.api_id).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="API app with this api_id already exists",
        )

    api_app = TelegramApiApp(
        api_id=payload.api_id,
        api_hash=payload.api_hash,
        app_title=payload.app_title,
        max_accounts=payload.max_accounts,
    )
    db.add(api_app)
    db.commit()
    db.refresh(api_app)
    return ApiAppCreateResponse.model_validate(api_app)


@router.get("/api-apps/{app_id}/reveal-hash", response_model=ApiAppHashReveal)
def reveal_api_app_hash(
    app_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("api_apps", "update")),
) -> ApiAppHashReveal:
    api_app = db.get(TelegramApiApp, app_id)
    if not api_app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API app not found")
    return ApiAppHashReveal(id=api_app.id, api_id=api_app.api_id, api_hash=api_app.api_hash)


@router.patch("/api-apps/{app_id}", response_model=ApiAppResponse)
def update_api_app(
    app_id: int,
    payload: ApiAppUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("api_apps", "update")),
) -> ApiAppResponse:
    api_app = db.get(TelegramApiApp, app_id)
    if not api_app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API app not found")

    update_data = payload.model_dump(exclude_unset=True)

    if "max_accounts" in update_data:
        linked_count = (
            db.query(func.count(TelegramAccount.id))
            .filter(TelegramAccount.api_app_id == app_id)
            .scalar()
        )
        if update_data["max_accounts"] < linked_count:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Невозможно установить max_accounts={update_data['max_accounts']}: "
                    f"к этому API-приложению привязано {linked_count} аккаунтов. "
                    f"Сначала открепите лишние аккаунты."
                ),
            )

    _UPDATE_FIELDS = {"api_hash", "app_title", "max_accounts", "is_active", "notes"}
    for field, value in update_data.items():
        if field not in _UPDATE_FIELDS:
            continue
        setattr(api_app, field, value)

    db.commit()
    db.refresh(api_app)
    return ApiAppResponse.model_validate(api_app)


@router.delete("/api-apps/{app_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_api_app(
    app_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_permission("api_apps", "delete")),
) -> None:
    api_app = db.get(TelegramApiApp, app_id)
    if not api_app:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API app not found")

    linked_count = db.query(func.count(TelegramAccount.id)).filter(
        TelegramAccount.api_app_id == app_id,
    ).scalar()
    if linked_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete: {linked_count} account(s) still linked to this API app",
        )

    db.delete(api_app)
    db.commit()
    return None
