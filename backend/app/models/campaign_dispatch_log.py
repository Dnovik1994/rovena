from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DispatchErrorType(str, Enum):
    flood_wait = "FloodWait"
    user_privacy_restricted = "UserPrivacyRestricted"
    peer_id_invalid = "PeerIdInvalid"
    user_blocked = "UserBlocked"
    other = "Other"


class CampaignDispatchLog(Base):
    __tablename__ = "campaign_dispatch_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(ForeignKey("campaigns.id"), index=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_accounts.id"), index=True)
    contact_id: Mapped[int | None] = mapped_column(ForeignKey("contacts.id"), index=True)
    error: Mapped[str] = mapped_column(String(255))
    error_type: Mapped[DispatchErrorType] = mapped_column(
        SqlEnum(DispatchErrorType), default=DispatchErrorType.other
    )
    error_message: Mapped[str | None] = mapped_column(String(255))
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
