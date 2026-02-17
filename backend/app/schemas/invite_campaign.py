"""Pydantic schemas for the InviteCampaign endpoints."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.sanitization import SanitizedModel


class InviteCampaignStatusEnum(str, Enum):
    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    error = "error"


class InviteCampaignCreate(SanitizedModel):
    name: str = Field(min_length=2, max_length=255)
    source_chat_id: int | None = None
    target_chat_id: int | None = None
    target_link: str | None = Field(default=None, max_length=500)
    target_title: str | None = Field(default=None, max_length=255)
    max_invites_total: int = Field(ge=1)
    invites_per_hour_per_account: int = Field(default=10, ge=1, le=100)
    max_accounts: int = Field(default=1, ge=1, le=50)


class InviteCampaignResponse(BaseModel):
    id: int
    owner_id: int
    name: str
    status: InviteCampaignStatusEnum
    source_chat_id: int | None
    source_title: str | None
    target_chat_id: int | None
    target_link: str | None
    target_title: str | None
    max_invites_total: int
    invites_per_hour_per_account: int
    max_accounts: int
    invites_completed: int
    invites_failed: int
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InviteCampaignDetailResponse(InviteCampaignResponse):
    total_tasks: int = 0
    pending: int = 0
    in_progress: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0


class ParsedChatInfo(BaseModel):
    chat_id: int
    title: str | None
    chat_type: str
    members_parsed: int
    last_parsed_at: datetime | None


class ParsedContactsSummaryResponse(BaseModel):
    total_contacts: int
    chats: list[ParsedChatInfo]


class AdminChatResponse(BaseModel):
    id: int
    chat_id: int
    title: str | None
    username: str | None
    chat_type: str
    members_count: int | None
