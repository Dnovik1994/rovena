from datetime import datetime, timedelta, timezone
from enum import Enum

from sqlalchemy import BigInteger, Boolean, DateTime, Enum as SqlEnum, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint, or_, update
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.core.database import Base
from app.clients.device_generator import generate_device_config


class TelegramAccountStatus(str, Enum):
    new = "new"
    code_sent = "code_sent"
    password_required = "password_required"
    verified = "verified"
    disconnected = "disconnected"
    error = "error"
    banned = "banned"
    warming = "warming"
    active = "active"
    cooldown = "cooldown"


class VerifyStatus(str, Enum):
    """Unified status for the verify pipeline."""
    pending = "pending"
    running = "running"
    needs_password = "needs_password"
    ok = "ok"
    failed = "failed"
    cooldown = "cooldown"


class VerifyReasonCode(str, Enum):
    """Normalized error reason codes for verify failures."""
    floodwait = "floodwait"
    bad_proxy = "bad_proxy"
    invalid_code = "invalid_code"
    password_required = "password_required"
    network = "network"
    client_disabled = "client_disabled"
    phone_invalid = "phone_invalid"
    code_expired = "code_expired"
    phone_banned = "phone_banned"
    session_revoked = "session_revoked"
    unknown = "unknown"


VERIFY_LEASE_TTL_SECONDS = 900  # 15 minutes


class TelegramAccount(Base):
    __tablename__ = "telegram_accounts"
    __table_args__ = (
        Index("ix_tg_accounts_owner_phone", "owner_user_id", "phone_e164", unique=True),
        Index("ix_tg_accounts_owner_id", "owner_user_id"),
        Index("ix_tg_accounts_status", "status"),
        UniqueConstraint("api_app_id", "proxy_id", name="uq_tg_accounts_api_app_proxy"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    owner_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    phone_e164: Mapped[str] = mapped_column(String(32), nullable=False)
    tg_user_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    tg_username: Mapped[str | None] = mapped_column(String(255), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[TelegramAccountStatus] = mapped_column(
        SqlEnum(TelegramAccountStatus), default=TelegramAccountStatus.new, nullable=False,
    )
    session_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_config: Mapped[dict | None] = mapped_column(JSON, default=generate_device_config)
    proxy_id: Mapped[int | None] = mapped_column(ForeignKey("proxies.id"), nullable=True)
    api_app_id: Mapped[int | None] = mapped_column(ForeignKey("telegram_api_apps.id"), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    api_app = relationship("TelegramApiApp", lazy="joined")

    # ── Verify lease/lock fields ──
    verifying: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, server_default="0")
    verifying_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verifying_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    verify_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    verify_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)

    warming_actions_completed: Mapped[int] = mapped_column(Integer, default=0)
    target_warming_actions: Mapped[int] = mapped_column(Integer, default=10)
    warming_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_activity_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_device_regenerated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def acquire_verify_lease(self, task_id: str, db: Session) -> bool:
        """Atomic lease acquisition using DB-level UPDATE with WHERE.

        Issues a single UPDATE ... WHERE that only succeeds if the row
        is not currently leased (or the existing lease has expired).
        Returns True if this worker acquired the lease, False otherwise.
        """
        from app.core.tz import ensure_utc
        now = ensure_utc(datetime.utcnow())
        lease_ttl = timedelta(seconds=VERIFY_LEASE_TTL_SECONDS)

        # Atomic: UPDATE only if not currently leased (or lease expired)
        result = db.execute(
            update(TelegramAccount)
            .where(
                TelegramAccount.id == self.id,
                or_(
                    TelegramAccount.verifying == False,  # noqa: E712
                    TelegramAccount.verifying_started_at == None,  # noqa: E711
                    TelegramAccount.verifying_started_at < now - lease_ttl,
                ),
            )
            .values(
                verifying=True,
                verifying_started_at=now,
                verifying_task_id=task_id,
                verify_status=VerifyStatus.running.value,
                verify_reason=None,
            )
        )
        db.commit()

        # If rowcount == 1, we got the lease. If 0, someone else has it.
        if result.rowcount == 1:
            db.refresh(self)
            return True
        return False

    def release_verify_lease(
        self,
        status: VerifyStatus,
        reason: VerifyReasonCode | None = None,
    ) -> None:
        """Release the verify lease and record the outcome."""
        self.verifying = False
        self.verifying_started_at = None
        self.verifying_task_id = None
        self.verify_status = status.value
        self.verify_reason = reason.value if reason else None
