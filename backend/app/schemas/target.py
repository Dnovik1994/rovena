from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.sanitization import SanitizedModel


class TargetType(str, Enum):
    group = "group"
    channel = "channel"


class TargetCreate(SanitizedModel):
    project_id: int
    name: str = Field(min_length=2, max_length=255)
    link: str = Field(min_length=5, max_length=255)
    type: TargetType


class TargetUpdate(SanitizedModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    link: str | None = Field(default=None, min_length=5, max_length=255)
    type: TargetType | None = None


class TargetResponse(BaseModel):
    id: int
    project_id: int
    owner_id: int
    name: str
    link: str
    type: TargetType
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
