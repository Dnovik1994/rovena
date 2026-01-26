import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.limits import get_daily_invites
from app.core.rate_limit import limiter, tariff_rate_limit
from app.models.account import Account
from app.models.campaign import Campaign, CampaignStatus
from app.models.project import Project
from app.models.user import User
from app.schemas.campaign import CampaignCreate, CampaignResponse, CampaignUpdate
from app.workers.tasks import campaign_dispatch

logger = logging.getLogger(__name__)

router = APIRouter(tags=["campaigns"])


@router.get("/campaigns", response_model=list[CampaignResponse])
async def list_campaigns(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[CampaignResponse]:
    campaigns = (
        db.query(Campaign)
        .filter(Campaign.owner_id == current_user.id)
        .order_by(Campaign.created_at.desc())
        .all()
    )
    return [CampaignResponse.model_validate(campaign) for campaign in campaigns]


@router.post("/campaigns", response_model=CampaignResponse, status_code=status.HTTP_201_CREATED)
async def create_campaign(
    payload: CampaignCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CampaignResponse:
    project = (
        db.query(Project)
        .filter(Project.id == payload.project_id, Project.owner_id == current_user.id)
        .first()
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    campaign = Campaign(
        project_id=payload.project_id,
        owner_id=current_user.id,
        source_id=payload.source_id,
        target_id=payload.target_id,
        name=payload.name,
        status=CampaignStatus.draft,
        max_invites_per_hour=payload.max_invites_per_hour,
        max_invites_per_day=payload.max_invites_per_day,
        start_at=payload.start_at,
        end_at=payload.end_at,
    )
    db.add(campaign)
    db.commit()
    db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.patch("/campaigns/{campaign_id}", response_model=CampaignResponse)
async def update_campaign(
    campaign_id: int,
    payload: CampaignUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CampaignResponse:
    campaign = (
        db.query(Campaign)
        .filter(Campaign.owner_id == current_user.id, Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        existing = db.get(Campaign, campaign_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )

    if payload.name is not None:
        campaign.name = payload.name
    if payload.status is not None:
        campaign.status = payload.status
    if payload.source_id is not None:
        campaign.source_id = payload.source_id
    if payload.target_id is not None:
        campaign.target_id = payload.target_id
    if payload.max_invites_per_hour is not None:
        campaign.max_invites_per_hour = payload.max_invites_per_hour
    if payload.max_invites_per_day is not None:
        campaign.max_invites_per_day = payload.max_invites_per_day
    if payload.start_at is not None:
        campaign.start_at = payload.start_at
    if payload.end_at is not None:
        campaign.end_at = payload.end_at

    db.commit()
    db.refresh(campaign)
    return CampaignResponse.model_validate(campaign)


@router.delete("/campaigns/{campaign_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    campaign = (
        db.query(Campaign)
        .filter(Campaign.owner_id == current_user.id, Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        existing = db.get(Campaign, campaign_id)
        if existing and existing.owner_id != current_user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )

    db.delete(campaign)
    db.commit()
    return None


@router.post("/campaigns/{campaign_id}/start", response_model=CampaignResponse)
@limiter.limit("5/minute")
@limiter.limit(tariff_rate_limit)
async def start_campaign(
    campaign_id: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CampaignResponse:
    campaign = (
        db.query(Campaign)
        .filter(Campaign.owner_id == current_user.id, Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )

    max_invites = current_user.tariff.max_invites_day if current_user.tariff else 50
    used_invites = get_daily_invites(current_user.id)
    if used_invites >= max_invites:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Daily invite limit reached",
        )

    max_accounts = current_user.tariff.max_accounts if current_user.tariff else 1
    account_count = db.query(Account).filter(Account.owner_id == current_user.id).count()
    if account_count > max_accounts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tariff account limit exceeded",
        )

    campaign.status = CampaignStatus.active
    campaign.progress = 0.0
    db.commit()
    db.refresh(campaign)

    logger.info("Campaign started", extra={"campaign_id": campaign.id})
    campaign_dispatch.delay(campaign.id)

    return CampaignResponse.model_validate(campaign)


@router.post("/campaigns/{campaign_id}/stop", response_model=CampaignResponse)
async def stop_campaign(
    campaign_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CampaignResponse:
    campaign = (
        db.query(Campaign)
        .filter(Campaign.owner_id == current_user.id, Campaign.id == campaign_id)
        .first()
    )
    if not campaign:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found"
        )

    campaign.status = CampaignStatus.paused
    db.commit()
    db.refresh(campaign)

    logger.info("Campaign paused", extra={"campaign_id": campaign.id})

    return CampaignResponse.model_validate(campaign)
