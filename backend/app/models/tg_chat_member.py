from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import BigInteger, DateTime, Enum as SqlEnum, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ChatMemberRole(str, Enum):
    owner = "owner"
    admin = "admin"
    member = "member"
    restricted = "restricted"
    banned = "banned"


class TgChatMember(Base):
    __tablename__ = "tg_chat_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("tg_users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[ChatMemberRole] = mapped_column(
        SqlEnum(ChatMemberRole), default=ChatMemberRole.member
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", name="uq_chat_member"),
    )
