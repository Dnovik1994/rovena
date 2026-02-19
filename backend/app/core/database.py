import asyncio
import logging
from typing import Any
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.cache import get_json, set_json
from app.core.settings import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)

connect_args = {}
engine_kwargs: dict[str, Any] = {
    "pool_pre_ping": True,
    "pool_recycle": 1800,
    "pool_reset_on_return": "rollback",
}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}
else:
    engine_kwargs.update(
        {
            "pool_timeout": 30,
            "pool_use_lifo": True,
            "pool_size": 20,
            "max_overflow": 5,
        }
    )

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    **engine_kwargs,
)
SessionLocal = sessionmaker(
    bind=engine,
    class_=Session,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_cached_user(db: Session, user_id: int):
    from app.models.user import User

    cache_key = f"user:{user_id}"
    cached = await get_json(cache_key)
    if cached:
        # Cache hit — load ORM object from the passed session so callers
        # always receive a consistent User instance.
        user = db.get(User, user_id)
        if user:
            return user
        # User disappeared from DB since caching — fall through to return None

    user = db.get(User, user_id)
    if not user:
        return None

    payload = {
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
    await set_json(cache_key, payload, settings.cache_ttl_seconds)
    return user


async def get_cached_tariff(db: Session, tariff_id: int):
    from app.models.tariff import Tariff

    cache_key = f"tariff:{tariff_id}"
    cached = await get_json(cache_key)
    if cached:
        return Tariff(**cached)

    def _load_tariff(tid: int):
        with SessionLocal() as s:
            return s.get(Tariff, tid)

    tariff = await asyncio.to_thread(_load_tariff, tariff_id)
    if not tariff:
        return None
    payload = {
        "id": tariff.id,
        "name": tariff.name,
        "max_accounts": tariff.max_accounts,
        "max_invites_day": tariff.max_invites_day,
        "price": tariff.price,
    }
    await set_json(cache_key, payload, settings.cache_ttl_seconds)
    return tariff
