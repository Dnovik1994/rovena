from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.errors import forbidden, unauthorized
from app.core.security import decode_access_token
from app.models.user import User


def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise unauthorized("Missing bearer token")

    token = authorization.replace("Bearer ", "", 1)
    try:
        payload = decode_access_token(token)
    except JWTError as exc:
        raise unauthorized("Invalid token") from exc

    user_id = payload.get("sub")
    if not user_id:
        raise unauthorized("Invalid token payload")

    user = db.get(User, int(user_id))
    if not user:
        raise unauthorized("User not found")

    request.state.user_id = user.id
    request.state.user = user
    return user


def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise forbidden("Admin access required")
    return current_user


def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise forbidden("Inactive user")
    return current_user
