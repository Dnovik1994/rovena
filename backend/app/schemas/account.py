from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.sanitization import SanitizedModel


class AccountStatus(str, Enum):
    new = "new"
    warming = "warming"
    active = "active"
    cooldown = "cooldown"
    blocked = "blocked"
    verified = "verified"


class AccountCreate(SanitizedModel):
    telegram_id: int
    user_id: int | None = None
    phone: str | None = Field(default=None, max_length=32)
    username: str | None = Field(default=None, max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    status: AccountStatus | None = None
    proxy_id: int | None = None
    device_config: dict | None = None


class AccountUpdate(SanitizedModel):
    phone: str | None = Field(default=None, max_length=32)
    username: str | None = Field(default=None, max_length=255)
    first_name: str | None = Field(default=None, max_length=255)
    status: AccountStatus | None = None
    proxy_id: int | None = None
    device_config: dict | None = None
    warming_started_at: datetime | None = None
    last_activity_at: datetime | None = None
    warming_actions_completed: int | None = Field(default=None, ge=0)
    target_warming_actions: int | None = Field(default=None, ge=0)
    cooldown_until: datetime | None = None
    last_device_regenerated_at: datetime | None = None


class AccountResponse(BaseModel):
    id: int
    user_id: int
    owner_id: int
    telegram_id: int
    phone: str | None
    username: str | None
    first_name: str | None
    status: AccountStatus
    proxy_id: int | None
    device_config: dict | None
    warming_actions_completed: int
    target_warming_actions: int
    warming_started_at: datetime | None
    last_activity_at: datetime | None
    cooldown_until: datetime | None
    last_device_regenerated_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AccountVerifyResponse(BaseModel):
    needs_password: bool = False
    account: AccountResponse | None = None
