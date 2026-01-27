from functools import lru_cache

from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.database import get_cached_tariff, get_cached_user, get_db
from app.core.errors import forbidden, unauthorized
from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.models.user import User


def _enforce_csrf(request: Request) -> None:
    settings = get_settings()
    if not settings.csrf_enabled:
        return
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token or csrf_token != settings.csrf_token:
            raise forbidden("CSRF token missing or invalid")


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> User:
    _enforce_csrf(request)
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

    user = await get_cached_user(db, int(user_id))
    if not user:
        raise unauthorized("User not found")

    if user.tariff_id and not getattr(user, "tariff", None):
        user.tariff = await get_cached_tariff(db, user.tariff_id)

    request.state.user_id = user.id
    request.state.user = user
    return user


async def get_current_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_admin:
        raise forbidden("Admin access required")
    return current_user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if not current_user.is_active:
        raise forbidden("Inactive user")
    return current_user


@lru_cache(maxsize=1024)
def _tariff_limits_cache(tariff_id: int, max_accounts: int, max_invites_day: int) -> dict[str, int]:
    return {"max_accounts": max_accounts, "max_invites_day": max_invites_day}


async def get_tariff_limits(current_user: User = Depends(get_current_user)) -> dict[str, int]:
    if current_user.tariff:
        return _tariff_limits_cache(
            current_user.tariff.id,
            current_user.tariff.max_accounts,
            current_user.tariff.max_invites_day,
        )
    return {"max_accounts": 1, "max_invites_day": 50}
