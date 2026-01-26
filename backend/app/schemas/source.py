from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SourceType(str, Enum):
    group = "group"
    channel = "channel"


class SourceCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=2, max_length=255)
    link: str = Field(min_length=5, max_length=255)
    type: SourceType


class SourceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    link: str | None = Field(default=None, min_length=5, max_length=255)
    type: SourceType | None = None


class SourceResponse(BaseModel):
    id: int
    project_id: int
    owner_id: int
    name: str
    link: str
    type: SourceType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
