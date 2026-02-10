from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.clients.device_generator import generate_device_config


class TelegramAccountStatus(str, Enum):
    new = "new"
    code_sent = "code_sent"
    password_required = "password_required"
    verified = "verified"
    disconnected = "disconnected"
    error = "error"
    banned = "banned"
    warming = "warming"
    active = "active"
    cooldown = "cooldown"


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    __table_args__ = (
        Index("ix_tg_accounts_owner_phone", "owner_user_id", "phone_e164", unique=True),
        Index("ix_tg_accounts_owner_id", "owner_user_id"),
        Index("ix_tg_accounts_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(32), nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tg_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[TelegramAccountStatus] = mapped_column(
        SqlEnum(TelegramAccountStatus), default=TelegramAccountStatus.new, nullable=False,
    )
    session_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_config: Mapped[dict | None] = mapped_column(JSON, default=generate_device_config)
    proxy_id: Mapped[int | None] = mapped_column(ForeignKey("proxies.id"), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    warming_actions_completed: Mapped[int] = mapped_column(Integer, default=0)
    target_warming_actions: Mapped[int] = mapped_column(Integer, default=10)
    warming_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_device_regenerated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
