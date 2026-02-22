import uuid
from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AuthFlowState(str, Enum):
    init = "init"
    code_sent = "code_sent"
    wait_code = "wait_code"
    code_submitted = "code_submitted"
    wait_password = "wait_password"
    password_submitted = "password_submitted"
    done = "done"
    expired = "expired"
    failed = "failed"


class TelegramAuthFlow(Base):
    __tablename__ = "telegram_auth_flows"
    __table_args__ = (
        Index("ix_auth_flows_account_id", "account_id"),
        Index("ix_auth_flows_expires_at", "expires_at"),
    )

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4()),
    )
    account_id: Mapped[int] = mapped_column(ForeignKey("telegram_accounts.id"), nullable=False)
    state: Mapped[AuthFlowState] = mapped_column(
        SqlEnum(AuthFlowState), default=AuthFlowState.init, nullable=False,
    )
    phone_e164: Mapped[str] = mapped_column(String(32), nullable=False)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    meta_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
