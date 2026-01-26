from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class ProxyType(str, Enum):
    http = "http"
    socks5 = "socks5"
    residential = "residential"


class ProxyStatus(str, Enum):
    active = "active"
    inactive = "inactive"
    error = "error"


class ProxyCreate(BaseModel):
    host: str = Field(min_length=1, max_length=255)
    port: int = Field(ge=1, le=65535)
    login: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    type: ProxyType
    country: str | None = Field(default=None, max_length=64)


class ProxyUpdate(BaseModel):
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    login: str | None = Field(default=None, max_length=255)
    password: str | None = Field(default=None, max_length=255)
    type: ProxyType | None = None
    country: str | None = Field(default=None, max_length=64)
    status: ProxyStatus | None = None
    uptime_seconds: int | None = Field(default=None, ge=0)
    latency_ms: int | None = Field(default=None, ge=0)


class ProxyResponse(BaseModel):
    id: int
    host: str
    port: int
    login: str | None
    password: str | None
    type: ProxyType
    country: str | None
    status: ProxyStatus
    last_check: datetime | None
    uptime_seconds: int
    latency_ms: int | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
