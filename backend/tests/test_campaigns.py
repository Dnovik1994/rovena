from fastapi import status
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.campaign import Campaign
from app.models.project import Project
from app.models.user import User


def _create_user(db: Session, telegram_id: int) -> User:
    user = User(telegram_id=telegram_id, username=f"user{telegram_id}")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_project(db: Session, owner_id: int, name: str) -> Project:
    project = Project(owner_id=owner_id, name=name, description=None)
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


def test_campaigns_crud_isolated(client):
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        user_one = _create_user(db, telegram_id=3001)
        user_two = _create_user(db, telegram_id=4002)
        project_one = _create_project(db, owner_id=user_one.id, name="Alpha")
        project_two = _create_project(db, owner_id=user_two.id, name="Beta")

        campaign_one = Campaign(
            project_id=project_one.id,
            owner_id=user_one.id,
            name="Campaign A",
        )
        campaign_two = Campaign(
            project_id=project_two.id,
            owner_id=user_two.id,
            name="Campaign B",
        )
        db.add_all([campaign_one, campaign_two])
        db.commit()

        token_one = create_access_token(str(user_one.id))
        token_two = create_access_token(str(user_two.id))
    finally:
        db.close()

    response_one = client.get(
        "/api/v1/campaigns", headers={"Authorization": f"Bearer {token_one}"}
    )
    response_two = client.get(
        "/api/v1/campaigns", headers={"Authorization": f"Bearer {token_two}"}
    )

    assert response_one.status_code == status.HTTP_200_OK
    assert response_two.status_code == status.HTTP_200_OK
    assert len(response_one.json()) == 1
    assert len(response_two.json()) == 1
    assert response_one.json()[0]["name"] == "Campaign A"
    assert response_two.json()[0]["name"] == "Campaign B"
