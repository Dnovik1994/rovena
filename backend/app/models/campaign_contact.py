from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InviteStatus(str, Enum):
    pending = "pending"
    invited = "invited"
    failed = "failed"
    already_member = "already_member"
    left = "left"
    flood_wait = "flood_wait"


class CampaignContact(Base):
    __tablename__ = "campaign_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tg_user_id: Mapped[int] = mapped_column(
        ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False
    )
    invite_status: Mapped[InviteStatus] = mapped_column(
        SqlEnum(InviteStatus), default=InviteStatus.pending
    )
    invited_by_account_id: Mapped[int | None] = mapped_column(
        ForeignKey("telegram_accounts.id")
    )
    invited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_message: Mapped[str | None] = mapped_column(String(500))
    attempts: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("campaign_id", "tg_user_id", name="uq_campaign_contact"),
    )
