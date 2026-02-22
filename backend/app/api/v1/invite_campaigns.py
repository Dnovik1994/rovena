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
    AdminChatResponse,
    InviteCampaignCreate,
    InviteCampaignDetailResponse,
    InviteCampaignResponse,
    ParsedContactsSummaryResponse,
    ParsedChatInfo,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["invite-campaigns"])


# ---------------------------------------------------------------------------
# GET /parsed-contacts/summary — parsed contacts grouped by chat
# ---------------------------------------------------------------------------
@router.get("/parsed-contacts/summary", response_model=ParsedContactsSummaryResponse)
def get_parsed_contacts_summary(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> ParsedContactsSummaryResponse:
    """Return parsed contacts summary with per-chat breakdown."""
    # Subquery: all account_ids belonging to the current user
    user_account_ids = (
        db.query(TelegramAccount.id)
        .filter(TelegramAccount.owner_user_id == current_user.id)
        .subquery()
    )

    # Total distinct contacts across all parsed chats
    total_contacts = (
        db.query(func.count(func.distinct(TgChatMember.user_id)))
        .join(TgAccountChat, TgAccountChat.chat_id == TgChatMember.chat_id)
        .filter(
            TgAccountChat.account_id.in_(db.query(user_account_ids.c.id)),
            TgAccountChat.last_parsed_at.isnot(None),
        )
        .scalar()
    ) or 0

    # Per-chat breakdown: only chats that were actually parsed
    chats_query = (
        db.query(
            TgAccountChat.chat_id,
            TgAccountChat.title,
            TgAccountChat.chat_type,
            TgAccountChat.last_parsed_at,
            func.count(func.distinct(TgChatMember.user_id)).label("members_parsed"),
        )
        .outerjoin(TgChatMember, TgChatMember.chat_id == TgAccountChat.chat_id)
        .filter(
            TgAccountChat.account_id.in_(db.query(user_account_ids.c.id)),
            TgAccountChat.last_parsed_at.isnot(None),
        )
        .group_by(
            TgAccountChat.chat_id,
            TgAccountChat.title,
            TgAccountChat.chat_type,
            TgAccountChat.last_parsed_at,
        )
        .order_by(func.count(func.distinct(TgChatMember.user_id)).desc())
        .all()
    )

    chats = [
        ParsedChatInfo(
            chat_id=row.chat_id,
            title=row.title,
            chat_type=row.chat_type,
            members_parsed=row.members_parsed,
            last_parsed_at=row.last_parsed_at,
        )
        for row in chats_query
    ]

    return ParsedContactsSummaryResponse(total_contacts=total_contacts, chats=chats)


# ---------------------------------------------------------------------------
# GET /my-admin-chats — chats where the user is admin/creator
# ---------------------------------------------------------------------------
@router.get("/my-admin-chats", response_model=list[AdminChatResponse])
def list_my_admin_chats(
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> list[AdminChatResponse]:
    """Return chats where the current user is admin or creator."""
    chats = (
        db.query(TgAccountChat)
        .join(TelegramAccount, TelegramAccount.id == TgAccountChat.account_id)
        .filter(
            TelegramAccount.owner_user_id == current_user.id,
            (TgAccountChat.is_admin.is_(True)) | (TgAccountChat.is_creator.is_(True)),
            TgAccountChat.chat_type.in_(["group", "supergroup", "channel"]),
        )
        .order_by(TgAccountChat.members_count.desc())
        .all()
    )

    return [
        AdminChatResponse(
            id=c.id,
            chat_id=c.chat_id,
            title=c.title,
            username=c.username,
            chat_type=c.chat_type,
            members_count=c.members_count,
        )
        for c in chats
    ]


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
    # Must have at least one of target_chat_id or target_link
    if not payload.target_chat_id and not payload.target_link:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Either target_chat_id or target_link must be provided",
        )

    source_title: str | None = None
    target_title = payload.target_title

    # Validate source_chat_id if provided
    if payload.source_chat_id is not None:
        source_chat = (
            db.query(TgAccountChat)
            .join(TelegramAccount, TelegramAccount.id == TgAccountChat.account_id)
            .filter(
                TgAccountChat.chat_id == payload.source_chat_id,
                TelegramAccount.owner_user_id == current_user.id,
            )
            .first()
        )
        if not source_chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="source_chat_id not found in your synced chats",
            )
        source_title = source_chat.title

    # Validate target_chat_id if provided
    if payload.target_chat_id is not None:
        target_chat = (
            db.query(TgAccountChat)
            .join(TelegramAccount, TelegramAccount.id == TgAccountChat.account_id)
            .filter(
                TgAccountChat.chat_id == payload.target_chat_id,
                TelegramAccount.owner_user_id == current_user.id,
                (TgAccountChat.is_admin.is_(True)) | (TgAccountChat.is_creator.is_(True)),
            )
            .first()
        )
        if not target_chat:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="target_chat_id not found in your admin chats",
            )
        target_title = target_chat.title

    campaign = InviteCampaign(
        owner_id=current_user.id,
        name=payload.name,
        status=InviteCampaignStatus.draft,
        source_chat_id=payload.source_chat_id,
        source_title=source_title,
        target_chat_id=payload.target_chat_id,
        target_link=payload.target_link,
        target_title=target_title,
        max_invites_total=payload.max_invites_total,
        invites_per_hour_per_account=payload.invites_per_hour_per_account,
        max_accounts=payload.max_accounts,
    )
    db.add(campaign)
    db.flush()  # get campaign.id

    # Exclude telegram_ids that belong to our own accounts
    own_tg_ids = [a.tg_user_id for a in db.query(TelegramAccount)
        .filter(TelegramAccount.owner_user_id == current_user.id)
        .filter(TelegramAccount.tg_user_id.isnot(None)).all()]

    # --- Cross-campaign deduplication ---
    # Determine target_chat_id to use for dedup (may differ from payload value)
    dedup_target_chat_id = payload.target_chat_id
    if payload.target_link and not dedup_target_chat_id:
        # Try to find target_chat_id from a previous campaign with the same link
        prev_campaign = db.query(InviteCampaign).filter(
            InviteCampaign.target_link == payload.target_link,
            InviteCampaign.target_chat_id.isnot(None),
        ).first()
        if prev_campaign:
            dedup_target_chat_id = prev_campaign.target_chat_id

    # Subquery: tg_user_ids already successfully invited to the same target
    already_invited_subq = None
    if dedup_target_chat_id:
        already_invited_subq = (
            db.query(InviteTask.tg_user_id)
            .join(InviteCampaign, InviteTask.campaign_id == InviteCampaign.id)
            .filter(
                InviteCampaign.target_chat_id == dedup_target_chat_id,
                InviteTask.status == InviteTaskStatus.success,
            )
            .subquery()
        )

    # Build members query depending on source_chat_id
    if payload.source_chat_id is not None:
        # Select tg_users from a specific chat
        members_query = (
            db.query(TgChatMember.user_id)
            .join(TgUser, TgUser.id == TgChatMember.user_id)
            .filter(TgChatMember.chat_id == payload.source_chat_id)
            .filter(TgUser.is_bot.is_(False))
            .filter(TgUser.is_deleted.is_(False))
        )
        if own_tg_ids:
            members_query = members_query.filter(~TgUser.telegram_id.in_(own_tg_ids))
        if already_invited_subq is not None:
            members_query = members_query.filter(
                ~TgChatMember.user_id.in_(db.query(already_invited_subq.c.tg_user_id))
            )
        members_query = members_query.order_by(
                case((TgUser.last_online_at.is_(None), 1), else_=0),
                TgUser.last_online_at.desc(),
            ).limit(payload.max_invites_total)
        user_ids = [row[0] for row in members_query.all()]
    else:
        # Select from ALL parsed contacts across user's accounts
        user_account_ids = (
            db.query(TelegramAccount.id)
            .filter(TelegramAccount.owner_user_id == current_user.id)
            .subquery()
        )
        members_query = (
            db.query(TgUser.id)
            .join(TgChatMember, TgChatMember.user_id == TgUser.id)
            .join(TgAccountChat, TgAccountChat.chat_id == TgChatMember.chat_id)
            .filter(
                TgAccountChat.account_id.in_(db.query(user_account_ids.c.id)),
                TgUser.is_bot.is_(False),
                TgUser.is_deleted.is_(False),
            )
        )
        if own_tg_ids:
            members_query = members_query.filter(~TgUser.telegram_id.in_(own_tg_ids))
        if already_invited_subq is not None:
            members_query = members_query.filter(
                ~TgUser.id.in_(db.query(already_invited_subq.c.tg_user_id))
            )
        members_query = members_query.group_by(TgUser.id).order_by(
                case((func.max(TgUser.last_online_at).is_(None), 1), else_=0),
                func.max(TgUser.last_online_at).desc(),
            ).limit(payload.max_invites_total)
        user_ids = [row[0] for row in members_query.all()]

    if not user_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No members found. Run account sync first.",
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
        "InviteCampaign created | id=%d owner=%d tasks=%d source=%s",
        campaign.id, current_user.id, tasks_created,
        payload.source_chat_id or "all",
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
