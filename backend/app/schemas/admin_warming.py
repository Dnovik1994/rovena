import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ── Warming Channels ──


class WarmingChannelCreate(BaseModel):
    username: str = Field(..., min_length=1, max_length=100)
    channel_type: Literal["channel", "group"]
    language: str = Field(default="uk", max_length=10)


class WarmingChannelResponse(BaseModel):
    id: int
    username: str
    channel_type: str
    language: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Warming Bios ──


class WarmingBioCreate(BaseModel):
    text: str = Field(..., min_length=1, max_length=200)


class WarmingBioResponse(BaseModel):
    id: int
    text: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Warming Photos ──


class WarmingPhotoResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    is_active: bool
    assigned_account_id: int | None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Warming Usernames ──

_USERNAME_TEMPLATE_RE = re.compile(r"^[a-z0-9_]+$")


class WarmingUsernameCreate(BaseModel):
    template: str = Field(..., min_length=1, max_length=100)

    @field_validator("template")
    @classmethod
    def validate_template(cls, v: str) -> str:
        if not _USERNAME_TEMPLATE_RE.match(v):
            raise ValueError("template must contain only [a-z0-9_]")
        return v


class WarmingUsernameResponse(BaseModel):
    id: int
    template: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Warming Names ──


class WarmingNameCreate(BaseModel):
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str | None = Field(default=None, max_length=100)


class WarmingNameResponse(BaseModel):
    id: int
    first_name: str
    last_name: str | None
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Trusted Accounts ──


class TrustedAccountToggle(BaseModel):
    is_trusted: bool


class TrustedAccountResponse(BaseModel):
    id: int
    phone_e164: str
    tg_username: str | None
    first_name: str | None
    last_name: str | None
    status: str
    is_trusted: bool
    warming_day: int
    created_at: datetime

    class Config:
        from_attributes = True


# ── Notification Settings ──


class NotificationSettingCreate(BaseModel):
    chat_id: str = Field(..., min_length=1, max_length=50)
    notify_account_banned: bool = True
    notify_flood_wait: bool = True
    notify_warming_failed: bool = True
    notify_system_health: bool = True
    notify_flood_rate_threshold: bool = True


class NotificationSettingUpdate(BaseModel):
    chat_id: str | None = Field(default=None, max_length=50)
    notify_account_banned: bool | None = None
    notify_flood_wait: bool | None = None
    notify_warming_failed: bool | None = None
    notify_system_health: bool | None = None
    notify_flood_rate_threshold: bool | None = None


class NotificationSettingResponse(BaseModel):
    id: int
    chat_id: str
    notify_account_banned: bool
    notify_flood_wait: bool
    notify_warming_failed: bool
    notify_system_health: bool
    notify_flood_rate_threshold: bool
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True
