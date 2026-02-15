from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class TelegramApiApp(Base):
    __tablename__ = "telegram_api_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    api_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    api_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    app_title: Mapped[str | None] = mapped_column(String(255))
    registered_phone: Mapped[str | None] = mapped_column(String(32))
    max_accounts: Mapped[int] = mapped_column(Integer, nullable=False, default=3, server_default="3")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
