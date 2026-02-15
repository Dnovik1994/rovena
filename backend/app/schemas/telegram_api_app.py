from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.sanitization import SanitizedModel


class ApiAppCreate(SanitizedModel):
    api_id: int = Field(ge=1)
    api_hash: str = Field(min_length=1, max_length=64)
    app_title: str | None = Field(default=None, max_length=255)
    max_accounts: int = Field(default=3, ge=1)


class ApiAppUpdate(SanitizedModel):
    api_hash: str | None = Field(default=None, min_length=1, max_length=64)
    app_title: str | None = Field(default=None, max_length=255)
    max_accounts: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class ApiAppResponse(BaseModel):
    id: int
    api_id: int
    api_hash: str
    app_title: str | None
    registered_phone: str | None
    max_accounts: int
    is_active: bool
    notes: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class ApiAppListResponse(ApiAppResponse):
    current_accounts_count: int
