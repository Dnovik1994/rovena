import re
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field, field_validator

_E164_PATTERN = re.compile(r"^\+[1-9]\d{6,14}$")


class TgAccountStatus(str, Enum):
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


class TgAccountCreate(BaseModel):
    phone: str = Field(..., min_length=7, max_length=32, examples=["+380501234567"])

    @field_validator("phone")
    @classmethod
    def validate_e164(cls, v: str) -> str:
        v = v.strip()
        if not _E164_PATTERN.match(v):
            raise ValueError("Phone must be in E.164 format (e.g. +380501234567)")
        return v


class TgAccountResponse(BaseModel):
    id: int
    owner_user_id: int
    phone_e164: str
    tg_user_id: int | None
    tg_username: str | None
    first_name: str | None
    last_name: str | None
    status: TgAccountStatus
    proxy_id: int | None
    device_config: dict | None
    last_error: str | None
    warming_actions_completed: int
    target_warming_actions: int
    warming_started_at: datetime | None
    cooldown_until: datetime | None
    last_activity_at: datetime | None
    last_device_regenerated_at: datetime | None
    created_at: datetime
    updated_at: datetime
    verified_at: datetime | None
    last_seen_at: datetime | None

    class Config:
        from_attributes = True


class SendCodeRequest(BaseModel):
    pass


class SendCodeResponse(BaseModel):
    flow_id: str
    status: TgAccountStatus
    message: str = "Verification code sent"


class ConfirmCodeRequest(BaseModel):
    flow_id: str
    code: str = Field(..., min_length=3, max_length=10)


class ConfirmCodeResponse(BaseModel):
    status: TgAccountStatus
    flow_id: str = ""
    state: str = ""
    next_step: str = ""
    needs_password: bool = False
    account: TgAccountResponse | None = None
    message: str = ""


class ConfirmPasswordRequest(BaseModel):
    flow_id: str
    password: str = Field(..., min_length=1, max_length=256)


class ConfirmPasswordResponse(BaseModel):
    status: TgAccountStatus
    flow_id: str = ""
    state: str = ""
    next_step: str = ""
    account: TgAccountResponse | None = None
    message: str = ""


class AuthFlowStatusResponse(BaseModel):
    flow_id: str
    flow_state: str
    account_status: TgAccountStatus
    last_error: str | None = None
    sent_at: datetime | None = None
    expires_at: datetime | None = None
    attempts: int = 0
