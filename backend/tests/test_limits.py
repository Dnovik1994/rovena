from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.core import limits
from app.models.campaign import Campaign, CampaignStatus
from app.models.project import Project
from app.models.tariff import Tariff
from app.models.user import User


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def pipeline(self):
        return self

    def incrby(self, key, amount):
        self.store[key] = int(self.store.get(key, 0)) + amount
        return self

    def expire(self, _key, _ttl):
        return True

    def execute(self):
        return True


def test_daily_limit_blocks_campaign_start(client, monkeypatch):
    fake_redis = FakeRedis()
    monkeypatch.setattr(limits, "get_redis_client", lambda: fake_redis)

    with SessionLocal() as db:
        tariff = Tariff(name="Tiny", max_accounts=1, max_invites_day=1, price=None)
        db.add(tariff)
        db.commit()
        db.refresh(tariff)

        user = User(telegram_id=4444, username="owner", tariff_id=tariff.id)
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

    limits.increment_daily_invites(user.id)

    token = create_access_token(str(user.id))
    response = client.post(
        f"/api/v1/campaigns/{campaign.id}/start",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == status.HTTP_429_TOO_MANY_REQUESTS
