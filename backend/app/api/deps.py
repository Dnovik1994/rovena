from typing import Any

from fastapi import Depends, Header, Request
from jose import JWTError
from sqlalchemy.orm import Session

from app.core.cache import cache, get_json, set_json
from app.core.database import get_cached_tariff, get_cached_user, get_db
from app.core.errors import forbidden, unauthorized
from app.core.security import decode_access_token
from app.core.settings import get_settings
from app.models.user import User


def _user_cache_key(user_id: int) -> str:
    return f"user:{user_id}"


def _cache_key_from_authorization(authorization: str | None) -> str | None:
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.replace("Bearer ", "", 1)
    try:
        payload = decode_access_token(token)
    except Exception:  # noqa: BLE001
        return None
    user_id = payload.get("sub")
    if not user_id:
        return None
    try:
        return _user_cache_key(int(user_id))
    except (ValueError, TypeError):
        return None


def _serialize_user(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "telegram_id": user.telegram_id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "is_admin": user.is_admin,
        "is_active": user.is_active,
        "role": user.role.value if getattr(user, "role", None) else None,
        "tariff_id": user.tariff_id,
    }


def _deserialize_user(payload: dict[str, Any]) -> User:
    from app.models.user import UserRole

    role_value = payload.get("role")
    if role_value:
        payload = {**payload, "role": UserRole(role_value)}
    return User(**payload)


def _set_request_state(user: User, request: Request) -> None:
    request.state.user_id = user.id
    request.state.user = user


def _enforce_csrf(request: Request) -> None:
    settings = get_settings()
    if not settings.csrf_enabled:
        return
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        csrf_token = request.headers.get("X-CSRF-Token")
        if not csrf_token or csrf_token != settings.csrf_token:
            raise forbidden("CSRF token missing or invalid")


@cache(
    ttl_seconds=60,
    key_builder=lambda request, db, authorization=None: _cache_key_from_authorization(authorization),
    serializer=_serialize_user,
    deserializer=_deserialize_user,
    on_hit=lambda user, request, db, authorization=None: _set_request_state(user, request),
)
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

    try:
        user_id_int = int(user_id)
    except (ValueError, TypeError) as exc:
        raise unauthorized("Invalid token payload") from exc

    user = await get_cached_user(db, user_id_int)
    if not user:
        raise unauthorized("User not found")

    if user.tariff_id and not getattr(user, "tariff", None):
        user.tariff = await get_cached_tariff(db, user.tariff_id)

    request.state.user_id = user.id
    request.state.user = user
    return user


@cache(
    ttl_seconds=60,
    key_builder=lambda current_user: _user_cache_key(current_user.id),
    serializer=_serialize_user,
    deserializer=_deserialize_user,
    validator=lambda user: getattr(user, "is_active", False),
)
async def get_current_active_user(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.is_active:
        raise forbidden("User inactive")
    return current_user


async def get_current_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    if not current_user.is_admin:
        raise forbidden("Admin access required")
    return current_user


def _tariff_limits_key(tariff_id: int) -> str:
    return f"tariff_limits:{tariff_id}"


async def get_tariff_limits(
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
    return {"max_accounts": 1, "max_invites_day": 50}
