from datetime import datetime, timedelta, timezone
import hashlib
from typing import Any

from jose import JWTError, jwt
from jose.exceptions import JWTClaimsError

from app.core.settings import get_settings

settings = get_settings()


def create_access_token(subject: str | int) -> str:
    expires_delta = timedelta(minutes=settings.jwt_expiration_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": str(subject), "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def create_refresh_token(subject: str | int) -> str:
    expires_delta = timedelta(days=settings.jwt_refresh_expiration_days)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": str(subject), "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _decode_token(token: str, token_type: str | None = None) -> dict[str, Any]:
    token = token.strip()
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        message = str(exc).lower()
        is_sub_error = isinstance(exc, JWTClaimsError) and (
            "subject" in message or "sub" in message
        )
        if not is_sub_error:
            raise
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
            options={"verify_sub": False},
        )
    payload_type = payload.get("type")
    if token_type and payload_type != token_type:
        raise JWTError("Invalid token type")
    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    return _decode_token(token, token_type="access")


def decode_refresh_token(token: str) -> dict[str, Any]:
    return _decode_token(token, token_type="refresh")
