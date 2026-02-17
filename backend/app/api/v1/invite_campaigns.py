"""API endpoints for the new InviteCampaign system."""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.models.invite_campaign import InviteCampaign, InviteCampaignStatus
from app.models.invite_task import InviteTask, InviteTaskStatus
from app.models.telegram_account import TelegramAccount
from app.models.tg_account_chat import TgAccountChat
from app.models.tg_chat_member import TgChatMember
from app.models.tg_user import TgUser
from app.models.user import User
from app.schemas.invite_campaign import (
    InviteCampaignCreate,
    InviteCampaignDetailResponse,
    InviteCampaignResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invite-campaigns"])


# ---------------------------------------------------------------------------
# POST /invite-campaigns — create campaign + generate invite tasks
# ---------------------------------------------------------------------------
@router.post(
    "/invite-campaigns",
    response_model=InviteCampaignDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_invite_campaign(
    payload: InviteCampaignCreate,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> InviteCampaignDetailResponse:
    # Verify source_chat_id exists in tg_account_chats owned by this user
    chat = (
        db.query(TgAccountChat)
        .join(TelegramAccount, TelegramAccount.id == TgAccountChat.account_id)
        .filter(
            TgAccountChat.chat_id == payload.source_chat_id,
            TelegramAccount.owner_user_id == current_user.id,
        )
        .first()
    )
    if not chat:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="source_chat_id not found in your synced chats",
        )

    campaign = InviteCampaign(
        owner_id=current_user.id,
        name=payload.name,
        status=InviteCampaignStatus.draft,
        source_chat_id=payload.source_chat_id,
        source_title=chat.title,
        target_link=payload.target_link,
        target_title=payload.target_title,
        max_invites_total=payload.max_invites_total,
        invites_per_hour_per_account=payload.invites_per_hour_per_account,
        max_accounts=payload.max_accounts,
    )
    db.add(campaign)
    db.flush()  # get campaign.id

    # Select tg_users from tg_chat_members for this chat,
    # ordered by last_online_at DESC (recently online first).
    members_query = (
        db.query(TgChatMember.user_id)
        .join(TgUser, TgUser.id == TgChatMember.user_id)
        .filter(TgChatMember.chat_id == payload.source_chat_id)
        .filter(TgUser.is_bot.is_(False))
        .filter(TgUser.is_deleted.is_(False))
        .order_by(
            case((TgUser.last_online_at.is_(None), 1), else_=0),
            TgUser.last_online_at.desc(),
        )
        .limit(payload.max_invites_total)
    )

    user_ids = [row[0] for row in members_query.all()]

    if not user_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No members found for this source chat. Run account sync first.",
        )

    tasks_created = 0
    for tg_user_id in user_ids:
        db.add(InviteTask(
            campaign_id=campaign.id,
            tg_user_id=tg_user_id,
            status=InviteTaskStatus.pending,
        ))
        tasks_created += 1

    db.commit()
    db.refresh(campaign)

    logger.info(
        "InviteCampaign created | id=%d owner=%d tasks=%d",
        campaign.id, current_user.id, tasks_created,
    )

    return InviteCampaignDetailResponse(
        **InviteCampaignResponse.model_validate(campaign).model_dump(),
        total_tasks=tasks_created,
        pending=tasks_created,
    )


# ---------------------------------------------------------------------------
# GET /invite-campaigns — list campaigns
# ---------------------------------------------------------------------------
@router.get("/invite-campaigns", response_model=list[InviteCampaignResponse])
def list_invite_campaigns(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> list[InviteCampaignResponse]:
    campaigns = (
        db.query(InviteCampaign)
        .filter(InviteCampaign.owner_id == current_user.id)
        .order_by(InviteCampaign.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [InviteCampaignResponse.model_validate(c) for c in campaigns]


# ---------------------------------------------------------------------------
# GET /invite-campaigns/{id} — detail with task progress
# ---------------------------------------------------------------------------
@router.get("/invite-campaigns/{campaign_id}", response_model=InviteCampaignDetailResponse)
def get_invite_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> InviteCampaignDetailResponse:
    campaign = (
        db.query(InviteCampaign)
        .filter(InviteCampaign.id == campaign_id, InviteCampaign.owner_id == current_user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    # Aggregate task statuses
    stats = (
        db.query(
            func.count(InviteTask.id).label("total"),
            func.sum(case((InviteTask.status == InviteTaskStatus.pending, 1), else_=0)).label("pending"),
            func.sum(case((InviteTask.status == InviteTaskStatus.in_progress, 1), else_=0)).label("in_progress"),
            func.sum(case((InviteTask.status == InviteTaskStatus.success, 1), else_=0)).label("success"),
            func.sum(case((InviteTask.status == InviteTaskStatus.failed, 1), else_=0)).label("failed"),
            func.sum(case((InviteTask.status == InviteTaskStatus.skipped, 1), else_=0)).label("skipped"),
        )
        .filter(InviteTask.campaign_id == campaign_id)
        .first()
    )

    return InviteCampaignDetailResponse(
        **InviteCampaignResponse.model_validate(campaign).model_dump(),
        total_tasks=stats.total or 0,
        pending=stats.pending or 0,
        in_progress=stats.in_progress or 0,
        success=stats.success or 0,
        failed=stats.failed or 0,
        skipped=stats.skipped or 0,
    )


# ---------------------------------------------------------------------------
# POST /invite-campaigns/{id}/start — launch campaign
# ---------------------------------------------------------------------------
@router.post("/invite-campaigns/{campaign_id}/start", response_model=InviteCampaignResponse)
def start_invite_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> InviteCampaignResponse:
    campaign = (
        db.query(InviteCampaign)
        .filter(InviteCampaign.id == campaign_id, InviteCampaign.owner_id == current_user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != InviteCampaignStatus.draft:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Campaign can only be started from draft status",
        )

    campaign.status = InviteCampaignStatus.active
    campaign.started_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(campaign)

    # Dispatch the celery task
    from app.workers.tg_invite_tasks import invite_campaign_dispatch

    try:
        invite_campaign_dispatch.delay(campaign.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("invite_campaign_dispatch enqueue failed: %s", exc)

    return InviteCampaignResponse.model_validate(campaign)


# ---------------------------------------------------------------------------
# POST /invite-campaigns/{id}/pause
# ---------------------------------------------------------------------------
@router.post("/invite-campaigns/{campaign_id}/pause", response_model=InviteCampaignResponse)
def pause_invite_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> InviteCampaignResponse:
    campaign = (
        db.query(InviteCampaign)
        .filter(InviteCampaign.id == campaign_id, InviteCampaign.owner_id == current_user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != InviteCampaignStatus.active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only active campaigns can be paused",
        )

    campaign.status = InviteCampaignStatus.paused
    db.commit()
    db.refresh(campaign)

    return InviteCampaignResponse.model_validate(campaign)


# ---------------------------------------------------------------------------
# POST /invite-campaigns/{id}/resume
# ---------------------------------------------------------------------------
@router.post("/invite-campaigns/{campaign_id}/resume", response_model=InviteCampaignResponse)
def resume_invite_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> InviteCampaignResponse:
    campaign = (
        db.query(InviteCampaign)
        .filter(InviteCampaign.id == campaign_id, InviteCampaign.owner_id == current_user.id)
        .first()
    )
    if not campaign:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")

    if campaign.status != InviteCampaignStatus.paused:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only paused campaigns can be resumed",
        )

    campaign.status = InviteCampaignStatus.active
    db.commit()
    db.refresh(campaign)

    from app.workers.tg_invite_tasks import invite_campaign_dispatch

    try:
        invite_campaign_dispatch.delay(campaign.id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("invite_campaign_dispatch enqueue failed: %s", exc)

    return InviteCampaignResponse.model_validate(campaign)
