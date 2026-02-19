from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.campaign import Campaign, CampaignStatus
from app.models.project import Project
from app.models.user import User


def test_rate_limit_start_campaign(client, monkeypatch):
    # Mock celery dispatch to prevent connection errors
    monkeypatch.setattr(
        "app.api.v1.campaigns.campaign_dispatch",
        type("FakeTask", (), {"delay": staticmethod(lambda *a, **kw: None)})(),
    )

    with SessionLocal() as db:
        user = User(telegram_id=3333, username="owner")
        db.add(user)
        db.commit()
        db.refresh(user)

        project = Project(owner_id=user.id, name="Project", description=None)
        db.add(project)
        db.commit()
        db.refresh(project)

        campaign = Campaign(
            project_id=project.id,
            owner_id=user.id,
            name="Test",
            status=CampaignStatus.draft,
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)

    token = create_access_token(str(user.id))

    for _ in range(5):
        response = client.post(
            f"/api/v1/campaigns/{campaign.id}/start",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code in {status.HTTP_200_OK, status.HTTP_429_TOO_MANY_REQUESTS}

    response = client.post(
        f"/api/v1/campaigns/{campaign.id}/start",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
