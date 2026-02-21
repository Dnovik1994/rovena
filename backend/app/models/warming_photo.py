from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class WarmingPhoto(Base):
    __tablename__ = "warming_photos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    assigned_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id"), nullable=True, unique=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )

    assigned_account = relationship(
        "TelegramAccount", uselist=False,
        foreign_keys=[assigned_account_id],
    )
