from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CampaignStatus(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("sources.id"), index=True)
    target_id: Mapped[int | None] = mapped_column(ForeignKey("targets.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[CampaignStatus] = mapped_column(
        SqlEnum(CampaignStatus), default=CampaignStatus.draft
    )
    max_invites_per_hour: Mapped[int] = mapped_column(Integer, default=1)
    max_invites_per_day: Mapped[int] = mapped_column(Integer, default=5)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    max_invites_total: Mapped[int | None] = mapped_column(Integer)
    invites_completed: Mapped[int] = mapped_column(Integer, default=0)
    invite_offset: Mapped[int] = mapped_column(Integer, default=0)
    source_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
