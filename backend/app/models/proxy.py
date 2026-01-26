from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import DateTime, Enum as SqlEnum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ProxyType(str, Enum):
    http = "http"
    socks5 = "socks5"
    residential = "residential"


class ProxyStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    error = "error"


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    login: Mapped[str | None] = mapped_column(String(255))
    password: Mapped[str | None] = mapped_column(String(255))
    type: Mapped[ProxyType] = mapped_column(SqlEnum(ProxyType))
    country: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[ProxyStatus] = mapped_column(SqlEnum(ProxyStatus), default=ProxyStatus.active)
    last_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    uptime_seconds: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
