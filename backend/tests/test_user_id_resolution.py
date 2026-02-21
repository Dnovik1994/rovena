"""Tests for TelegramAccount isolation, celery task registration, and admin checkout."""
from unittest.mock import patch

from fastapi import status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.user import User, UserRole


def _create_user(
    db: Session, telegram_id: int, is_admin: bool = False,
) -> User:
    user = User(
        telegram_id=telegram_id,
        username=f"user{telegram_id}",
        is_admin=is_admin,
        role=UserRole.admin if is_admin else UserRole.user,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_tg_account_owner_isolation(client):
    """Each user can only see their own TelegramAccounts."""
    with SessionLocal() as db:
        user = _create_user(db, telegram_id=90001)
        other = _create_user(db, telegram_id=90002)
        token = create_access_token(str(user.id))

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=300001,
            phone_e164="+10000300001",
            status=TelegramAccountStatus.new,
        )
        other_account = TelegramAccount(
            owner_user_id=other.id,
            tg_user_id=300002,
            phone_e164="+10000300002",
            status=TelegramAccountStatus.new,
        )
        db.add_all([account, other_account])
        db.commit()

    resp = client.get(
        "/api/v1/tg-accounts",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data) == 1
    assert data[0]["tg_user_id"] == 300001


def test_tg_account_fk_integrity(client):
    """TelegramAccount.owner_user_id must always be a valid users.id."""
    with SessionLocal() as db:
        user = _create_user(db, telegram_id=90006)

        account = TelegramAccount(
            owner_user_id=user.id,
            tg_user_id=400004,
            phone_e164="+10000400004",
            status=TelegramAccountStatus.new,
        )
        db.add(account)
        db.commit()
        db.refresh(account)

        # Verify FK integrity: owner_user_id points to an existing user
        linked_user = db.get(User, account.owner_user_id)
        assert linked_user is not None
        assert linked_user.id == user.id


def test_celery_tasks_are_registered():
    """All expected Celery tasks must be registered in the app."""
    from app.workers import celery_app
    # Importing the tasks module forces @celery_app.task decorators to fire,
    # which is what happens in production when the worker or web process starts.
    import app.workers.tasks  # noqa: F401

    registered = celery_app.tasks.keys()
    expected_tasks = [
        "app.workers.tasks.campaign_dispatch",
        "app.workers.tasks.account_health_check",
        "app.workers.tasks.sync_3proxy_config",
        "app.workers.tasks.validate_proxy_task",
    ]
    for task_name in expected_tasks:
        assert task_name in registered, f"Task {task_name} is not registered"


def test_admin_checkout_resolves_telegram_id(client):
    """Admin checkout should resolve telegram_id passed as user_id."""
    with SessionLocal() as db:
        admin = _create_user(db, telegram_id=90007, is_admin=True)
        target = _create_user(db, telegram_id=888999000)
        token = create_access_token(str(admin.id))

    with (
        patch("app.api.v1.admin.settings") as mock_settings,
        patch("app.api.v1.admin.stripe") as mock_stripe,
    ):
        mock_settings.stripe_secret_key = "sk_test_fake"
        mock_settings.web_base_url = "http://localhost"
        mock_session = type("Session", (), {"url": "https://checkout.stripe.com/test"})()
        mock_stripe.checkout.Session.create.return_value = mock_session

        resp = client.post(
            "/api/v1/admin/subscriptions/create-checkout",
            json={"tariff_id": 1, "user_id": 888999000},  # telegram_id
            headers={"Authorization": f"Bearer {token}"},
        )

    # Should not be 500; the user should be resolved
    assert resp.status_code == 200


def test_admin_checkout_invalid_user_returns_422(client):
    """Admin checkout with nonexistent user_id should return 422."""
    with SessionLocal() as db:
        admin = _create_user(db, telegram_id=90008, is_admin=True)
        token = create_access_token(str(admin.id))

    with patch("app.api.v1.admin.settings") as mock_settings:
        mock_settings.stripe_secret_key = "sk_test_fake"

        resp = client.post(
            "/api/v1/admin/subscriptions/create-checkout",
            json={"tariff_id": 1, "user_id": 9999999},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
