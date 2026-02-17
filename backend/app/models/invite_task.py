"""InviteTask — individual invite job within an InviteCampaign."""

from datetime import datetime
from enum import Enum

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InviteTaskStatus(str, Enum):
    pending = "pending"
    in_progress = "in_progress"
    success = "success"
    failed = "failed"
    skipped = "skipped"  # already member, bot, etc.


class InviteTask(Base):
    __tablename__ = "invite_tasks"
    __table_args__ = (
        UniqueConstraint("campaign_id", "tg_user_id", name="uq_invite_task"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    campaign_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("invite_campaigns.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tg_user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tg_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    account_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("telegram_accounts.id"),
        nullable=True,
    )
    status: Mapped[InviteTaskStatus] = mapped_column(
        SqlEnum(InviteTaskStatus), default=InviteTaskStatus.pending,
    )
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)
    attempted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
