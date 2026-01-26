import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token
from app.models.user import User
from app.schemas.auth import TelegramAuthRequest, TokenResponse
from app.services.telegram_auth import TelegramAuthError, validate_init_data

router = APIRouter(tags=["auth"])


@router.post("/auth/telegram", response_model=TokenResponse)
async def auth_via_telegram(
    payload: TelegramAuthRequest, db: Session = Depends(get_db)
) -> TokenResponse:
    try:
        data = validate_init_data(payload.init_data)
    except TelegramAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing user in initData",
        )

    user_payload = json.loads(user_raw)
    telegram_id = int(user_payload["id"])

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

    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)
