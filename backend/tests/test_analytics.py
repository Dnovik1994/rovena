from datetime import datetime, timedelta, timezone

from fastapi import status
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.campaign import Campaign, CampaignStatus
from app.models.project import Project
from app.models.user import User


def _create_user(db: Session, telegram_id: int) -> User:
    user = User(telegram_id=telegram_id, username=f"user{telegram_id}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_dashboard_analytics_series(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user = _create_user(db, telegram_id=3001)
        project = Project(owner_id=user.id, name="Project", description=None)
        db.add(project)
        db.commit()
        db.refresh(project)

        today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        two_days_ago = today - timedelta(days=2)

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=999001,
            phone_e164="+10000999001",
            status=TelegramAccountStatus.active,
            created_at=two_days_ago,
        )
        campaign = Campaign(
            project_id=project.id,
            owner_id=user.id,
            name="Launch",
            status=CampaignStatus.active,
            created_at=today,
        )
        db.add_all([account, campaign])
        db.commit()

        token = create_access_token(str(user.id))
    finally:
        db.close()

    response = client.get(
        "/api/v1/analytics/dashboard?window_days=7",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_200_OK
    payload = response.json()
    assert payload["window_days"] == 7
    assert len(payload["accounts_created"]) == 7
    assert len(payload["campaigns_created"]) == 7
    assert payload["totals"]["accounts"] == 1
    assert payload["totals"]["campaigns"] == 1
