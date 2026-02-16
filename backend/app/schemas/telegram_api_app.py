from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.schemas.sanitization import SanitizedModel


def mask_api_hash(value: str) -> str:
    """Mask api_hash showing only first 4 and last 4 characters."""
    if len(value) <= 8:
        return "****"
    return f"{value[:4]}...{value[-4:]}"


class ApiAppCreate(SanitizedModel):
    api_id: int = Field(ge=1)
    api_hash: str = Field(min_length=1, max_length=64)
    app_title: str | None = Field(default=None, max_length=255)
    max_accounts: int = Field(default=3, ge=1)
    registered_phone: str | None = Field(default=None, max_length=20)
    notes: str | None = Field(default=None, max_length=2000)


class ApiAppUpdate(SanitizedModel):
    api_hash: str | None = Field(default=None, min_length=1, max_length=64)
    app_title: str | None = Field(default=None, max_length=255)
    max_accounts: int | None = Field(default=None, ge=1)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class _ApiAppBase(BaseModel):
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


class ApiAppResponse(_ApiAppBase):
    """Default response — api_hash is masked."""

    @model_validator(mode="after")
    def _mask_hash(self) -> "ApiAppResponse":
        object.__setattr__(self, "api_hash", mask_api_hash(self.api_hash))
        return self


class ApiAppCreateResponse(_ApiAppBase):
    """Returned once on POST — full api_hash visible."""


class ApiAppHashReveal(BaseModel):
    id: int
    api_id: int
    api_hash: str


class ApiAppListResponse(ApiAppResponse):
    current_accounts_count: int
