from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.database import get_db
from app.models.account import Account
from app.models.campaign import Campaign
from app.models.user import User
from app.schemas.analytics import DashboardAnalyticsResponse, AnalyticsPoint

router = APIRouter(tags=["analytics"])


def _build_series(
    rows: list[tuple[date, int]], start_date: date, window_days: int
) -> list[AnalyticsPoint]:
    mapping = {row_date: count for row_date, count in rows}
    series: list[AnalyticsPoint] = []
    for offset in range(window_days):
        current = start_date + timedelta(days=offset)
        series.append(AnalyticsPoint(date=current.isoformat(), value=mapping.get(current, 0)))
    return series


@router.get("/analytics/dashboard", response_model=DashboardAnalyticsResponse)
async def dashboard_analytics(
    window_days: int = Query(default=14, ge=7, le=60),
    current_user: User = Depends(get_current_active_user),
    db: Session = Depends(get_db),
) -> DashboardAnalyticsResponse:
    start_date = datetime.now(timezone.utc).date() - timedelta(days=window_days - 1)
    start_dt = datetime.combine(start_date, datetime.min.time(), tzinfo=timezone.utc)

    account_rows = (
        db.query(func.date(Account.created_at), func.count(Account.id))
        .filter(Account.owner_id == current_user.id, Account.created_at >= start_dt)
        .group_by(func.date(Account.created_at))
        .all()
    )
    campaign_rows = (
        db.query(func.date(Campaign.created_at), func.count(Campaign.id))
        .filter(Campaign.owner_id == current_user.id, Campaign.created_at >= start_dt)
        .group_by(func.date(Campaign.created_at))
        .all()
    )

    accounts_created = _build_series(account_rows, start_date, window_days)
    campaigns_created = _build_series(campaign_rows, start_date, window_days)

    totals = {
        "accounts": db.query(Account).filter(Account.owner_id == current_user.id).count(),
        "campaigns": db.query(Campaign).filter(Campaign.owner_id == current_user.id).count(),
    }

    return DashboardAnalyticsResponse(
        window_days=window_days,
        accounts_created=accounts_created,
        campaigns_created=campaigns_created,
        totals=totals,
    )
