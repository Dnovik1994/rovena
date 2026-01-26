from datetime import datetime

from pydantic import BaseModel, Field


class ContactCreate(BaseModel):
    project_id: int
    telegram_id: int
    first_name: str = Field(min_length=1, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = None
    source_id: int | None = None


class ContactUpdate(BaseModel):
    first_name: str | None = Field(default=None, min_length=1, max_length=255)
    last_name: str | None = Field(default=None, max_length=255)
    username: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    tags: list[str] | None = None


class ContactResponse(BaseModel):
    id: int
    project_id: int
    owner_id: int
    telegram_id: int
    first_name: str
    last_name: str | None
    username: str | None
    phone: str | None
    tags: list[str] | None
    source_id: int | None
    blocked: bool
    blocked_reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True
