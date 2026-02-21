from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AdminNotificationSetting(Base):
    __tablename__ = "admin_notification_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[str] = mapped_column(String(50), nullable=False)
    notify_account_banned: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_flood_wait: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_warming_failed: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_warming_completed: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_system_health: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_flood_rate_threshold: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
