from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class CampaignStatus(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"


class CampaignCreate(BaseModel):
    project_id: int
    name: str = Field(min_length=2, max_length=255)
    source_id: int | None = None
    target_id: int | None = None
    max_invites_per_hour: int = Field(default=1, ge=1)
    max_invites_per_day: int = Field(default=5, ge=1)
    start_at: datetime | None = None
    end_at: datetime | None = None


class CampaignUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    status: CampaignStatus | None = None
    source_id: int | None = None
    target_id: int | None = None
    max_invites_per_hour: int | None = Field(default=None, ge=1)
    max_invites_per_day: int | None = Field(default=None, ge=1)
    start_at: datetime | None = None
    end_at: datetime | None = None


class CampaignResponse(BaseModel):
    id: int
    project_id: int
    owner_id: int
    name: str
    status: CampaignStatus
    source_id: int | None
    target_id: int | None
    max_invites_per_hour: int
    max_invites_per_day: int
    progress: float
    start_at: datetime | None
    end_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True
