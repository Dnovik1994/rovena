# TODO: DEPRECATED — эта модель не поддерживает per-account api_id.
# Все новые задачи должны использовать TelegramAccount.
# План: мигрировать tasks.py на TelegramAccount, затем удалить эту модель.

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, ForeignKey, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.clients.device_generator import generate_device_config


class AccountStatus(str, Enum):
    new = "new"
    warming = "warming"
    active = "active"
    cooldown = "cooldown"
    blocked = "blocked"
    verified = "verified"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    username: Mapped[str | None] = mapped_column(String(255))
    first_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[AccountStatus] = mapped_column(SqlEnum(AccountStatus), default=AccountStatus.new)
    proxy_id: Mapped[int | None] = mapped_column(ForeignKey("proxies.id"), index=True)
    device_config: Mapped[dict | None] = mapped_column(JSON, default=generate_device_config)
    last_device_regenerated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    warming_actions_completed: Mapped[int] = mapped_column(Integer, default=0)
    target_warming_actions: Mapped[int] = mapped_column(Integer, default=10)
    warming_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
