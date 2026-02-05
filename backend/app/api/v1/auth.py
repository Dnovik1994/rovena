import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_token,
)
from app.core.settings import get_settings
from app.models.user import User
from app.schemas.auth import RefreshTokenRequest, TelegramAuthRequest, TokenResponse
from app.services.telegram_auth import TelegramAuthError, validate_init_data

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(tags=["auth"])


@router.post("/auth/telegram", response_model=TokenResponse)
@limiter.limit("10/minute")
async def auth_via_telegram(
    request: Request,
    payload: TelegramAuthRequest,
    db: Session = Depends(get_db),
) -> TokenResponse:
    if not settings.telegram_auth_enabled:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Telegram auth is disabled",
        )

    try:
        data = validate_init_data(payload.init_data)
    except TelegramAuthError as exc:
        logger.warning("Telegram auth failed", extra={"error": str(exc)})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication failed") from exc

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
    if not user:
        user = User(
            telegram_id=telegram_id,
            username=user_payload.get("username"),
            first_name=user_payload.get("first_name"),
            last_name=user_payload.get("last_name"),
            is_admin=False,
            is_active=True,
            role="user",
        )
        db.add(user)
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
    )


@router.post("/auth/refresh", response_model=TokenResponse)
@limiter.limit("20/minute")
async def refresh_access_token(
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
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)
