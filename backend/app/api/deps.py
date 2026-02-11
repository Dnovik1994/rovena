from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.cache import get_json, set_json
from app.core.database import get_cached_tariff, get_db
from app.core.errors import forbidden, unauthorized
from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.models.user import User


def _user_cache_key(user_id: int) -> str:
    return f"user:{user_id}"


def _enforce_csrf(request: Request) -> None:
    settings = get_settings()
    if not settings.csrf_enabled:
        return
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token or csrf_token != settings.csrf_token:
            raise forbidden("CSRF token missing or invalid")


async def get_current_user_id(
    request: Request,
    authorization: str | None = Header(default=None),
) -> int:
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

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError) as exc:
        raise unauthorized("Invalid token payload") from exc

    request.state.user_id = user_id_int
    return user_id_int


def get_current_active_user(
    db: Session = Depends(get_db),
    current_user_id: int = Depends(get_current_user_id),
) -> User:
    """Synchronous so FastAPI runs it in a threadpool, keeping the event loop free."""
    user = db.get(User, current_user_id)
    if not user:
        raise unauthorized("User not found")
    if not user.is_active:
        raise forbidden("User inactive")
    return user


def get_current_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if not current_user.has_admin_access:
        raise forbidden("Admin access required")
    return current_user


def _tariff_limits_key(tariff_id: int) -> str:
    return f"tariff_limits:{tariff_id}"


async def get_tariff_limits(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> dict[str, int]:
    if current_user.tariff:
        cache_key = _tariff_limits_key(current_user.tariff.id)
        cached = await get_json(cache_key)
        if cached:
            return {
                "max_accounts": cached.get("max_accounts", current_user.tariff.max_accounts),
                "max_invites_day": cached.get("max_invites_day", current_user.tariff.max_invites_day),
            }
        payload = {
            "max_accounts": current_user.tariff.max_accounts,
            "max_invites_day": current_user.tariff.max_invites_day,
        }
        await set_json(cache_key, payload, ttl_seconds=60)
        return payload

    if current_user.tariff_id:
        tariff = await get_cached_tariff(db, current_user.tariff_id)
        if tariff:
            return {
                "max_accounts": tariff.max_accounts,
                "max_invites_day": tariff.max_invites_day,
            }

    return {"max_accounts": 1, "max_invites_day": 50}
