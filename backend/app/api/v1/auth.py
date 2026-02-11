import json
import logging
import time
from typing import Any
from urllib.parse import parse_qsl

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.metrics import telegram_auth_reject_total
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
)
from app.models.user import ADMIN_ROLES, User, UserRole
from app.schemas.auth import RefreshTokenRequest, TelegramAuthRequest, TokenResponse
from app.services.telegram_auth import TelegramAuthError, validate_init_data

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])


def _is_configured_admin(telegram_id: int) -> bool:
    """Check whether *telegram_id* matches the configured ADMIN_TELEGRAM_ID."""
    from app.core.settings import get_settings

    admin_tid = get_settings().admin_telegram_id
    if admin_tid is None:
        return False
    return telegram_id == admin_tid


def _extract_init_data_metadata(init_data: str) -> dict[str, Any]:
    metadata: dict[str, Any] = {"auth_date": None, "hash_prefix": None}
    if not init_data:
        return metadata
    try:
        parsed = dict(parse_qsl(init_data, strict_parsing=False))
    except ValueError:
        return metadata
    hash_value = parsed.get("hash")
    if hash_value:
        metadata["hash_prefix"] = hash_value[:8]
    auth_date_raw = parsed.get("auth_date")
    if auth_date_raw:
        try:
            metadata["auth_date"] = int(auth_date_raw)
        except ValueError:
            metadata["auth_date"] = None
    return metadata


@router.post("/auth/telegram", response_model=TokenResponse)
@limiter.limit("10/minute")
def auth_via_telegram(
    request: Request,
    payload: TelegramAuthRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    try:
        data = validate_init_data(payload.init_data)
    except TelegramAuthError as exc:
        init_data = payload.init_data or ""
        metadata = _extract_init_data_metadata(init_data)
        telegram_auth_reject_total.labels(reason=exc.reason_code).inc()
        logger.warning(
            "Telegram auth failed: %s",
            str(exc),
            extra={
                "reason_code": exc.reason_code,
                "init_data_len": len(init_data),
                "has_hash": "hash=" in init_data,
                "hash_prefix": exc.hash_prefix or metadata["hash_prefix"],
                "auth_date": exc.auth_date or metadata["auth_date"],
                "server_time": int(time.time()),
            },
        )
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={
                "error": {
                    "code": str(status.HTTP_401_UNAUTHORIZED),
                    "message": "Authentication failed",
                    "reason_code": exc.reason_code,
                }
            },
        )

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing user in initData",
        )

    try:
        user_payload = json.loads(user_raw)
        telegram_id = int(user_payload["id"])
    except (json.JSONDecodeError, KeyError, ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid user data in initData",
        ) from exc

    user = db.query(User).filter(User.telegram_id == telegram_id).first()
    should_be_admin = _is_configured_admin(telegram_id)
    if not user:
        role = UserRole.admin if should_be_admin else UserRole.user
        user = User(
            telegram_id=telegram_id,
            username=user_payload.get("username"),
            first_name=user_payload.get("first_name"),
            last_name=user_payload.get("last_name"),
            is_admin=role in ADMIN_ROLES,
            is_active=True,
            role=role,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    elif should_be_admin and user.role not in ADMIN_ROLES:
        # Only promote — never downgrade an existing admin/superadmin.
        user.role = UserRole.admin
        user.is_admin = True
        db.commit()
        db.refresh(user)

    access_token = create_access_token(str(user.id))
    refresh_token = create_refresh_token(str(user.id))
    user.refresh_token = hash_token(refresh_token)
    db.commit()
    onboarding_needed = not user.onboarding_completed
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        onboarding_needed=onboarding_needed,
        is_admin=user.has_admin_access,
        role=user.role.value if user.role else None,
    )


@router.post("/auth/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
def refresh_access_token(
    request: Request,
    payload: RefreshTokenRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    try:
        token_payload = decode_refresh_token(payload.refresh_token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token") from exc

    user_id = token_payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    if not user.refresh_token or user.refresh_token != hash_token(payload.refresh_token):
        # Possible token reuse attack — invalidate all refresh tokens for this user
        user.refresh_token = None
        db.commit()
        logger.warning(
            "Refresh token mismatch — possible reuse attack",
            extra={"user_id": user.id},
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token mismatch")

    access_token = create_access_token(str(user.id))
    new_refresh_token = create_refresh_token(str(user.id))
    user.refresh_token = hash_token(new_refresh_token)
    db.commit()
    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        is_admin=user.has_admin_access,
        role=user.role.value if user.role else None,
    )
