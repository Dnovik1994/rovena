from datetime import datetime, timedelta, timezone

from jose import jwt

from app.core.settings import get_settings

settings = get_settings()


def create_access_token(subject: str) -> str:
    expires_delta = timedelta(minutes=settings.jwt_expiration_minutes)
    expire = datetime.now(timezone.utc) + expires_delta
    payload = {"sub": subject, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
