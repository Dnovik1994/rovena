"""InviteCampaign — new invite system (separate from legacy Campaign)."""

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SqlEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InviteCampaignStatus(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    error = "error"


class InviteCampaign(Base):
    __tablename__ = "invite_campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[InviteCampaignStatus] = mapped_column(
        SqlEnum(InviteCampaignStatus), default=InviteCampaignStatus.draft,
    )

    # Source: where to get contacts — Telegram chat ID
    source_chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Target: where to add members
    target_link: Mapped[str] = mapped_column(String(500), nullable=False)
    target_title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Limits
    max_invites_total: Mapped[int] = mapped_column(Integer, nullable=False)
    invites_per_hour_per_account: Mapped[int] = mapped_column(Integer, default=10)
    max_accounts: Mapped[int] = mapped_column(Integer, default=1)

    # Progress
    invites_completed: Mapped[int] = mapped_column(Integer, default=0)
    invites_failed: Mapped[int] = mapped_column(Integer, default=0)

    # Timestamps
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
