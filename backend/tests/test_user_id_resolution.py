"""Tests for user_id resolution, FK integrity, and celery task registration."""
from unittest.mock import patch

from fastapi import status
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.account import Account
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


def test_create_account_defaults_user_id_to_current_user(client):
    """When user_id is omitted, account.user_id should be set to current_user.id."""
    with SessionLocal() as db:
        user = _create_user(db, telegram_id=90001)
        token = create_access_token(str(user.id))

    with patch("app.api.v1.accounts.account_health_check"):
        resp = client.post(
            "/api/v1/accounts",
            json={"telegram_id": 300001},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["user_id"] == user.id
    assert data["owner_id"] == user.id


def test_create_account_resolves_telegram_id_as_user_id(client):
    """When frontend sends telegram_id in user_id field, backend resolves it."""
    with SessionLocal() as db:
        admin = _create_user(db, telegram_id=90002, is_admin=True)
        target = _create_user(db, telegram_id=777888999)
        token = create_access_token(str(admin.id))

    with patch("app.api.v1.accounts.account_health_check"):
        resp = client.post(
            "/api/v1/accounts",
            json={
                "telegram_id": 400001,
                "user_id": 777888999,  # telegram_id, not users.id
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    # Should have resolved telegram_id 777888999 to target.id
    assert data["user_id"] == target.id


def test_create_account_rejects_invalid_user_id(client):
    """When user_id does not match any user, return 422."""
    with SessionLocal() as db:
        admin = _create_user(db, telegram_id=90003, is_admin=True)
        token = create_access_token(str(admin.id))

    with patch("app.api.v1.accounts.account_health_check"):
        resp = client.post(
            "/api/v1/accounts",
            json={
                "telegram_id": 400002,
                "user_id": 9999999,  # nonexistent
            },
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_account_non_admin_cannot_set_other_user_id(client):
    """Non-admin users can only create accounts for themselves."""
    with SessionLocal() as db:
        user = _create_user(db, telegram_id=90004)
        other = _create_user(db, telegram_id=90005)
        token = create_access_token(str(user.id))

    with patch("app.api.v1.accounts.account_health_check"):
        resp = client.post(
            "/api/v1/accounts",
            json={"telegram_id": 400003, "user_id": other.id},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == status.HTTP_403_FORBIDDEN


def test_create_account_fk_integrity_user_id_is_valid(client):
    """Account.user_id must always be a valid users.id after creation."""
    with SessionLocal() as db:
        user = _create_user(db, telegram_id=90006)
        token = create_access_token(str(user.id))

    with patch("app.api.v1.accounts.account_health_check"):
        resp = client.post(
            "/api/v1/accounts",
            json={"telegram_id": 400004},
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == status.HTTP_201_CREATED
    account_id = resp.json()["id"]

    with SessionLocal() as db:
        account = db.get(Account, account_id)
        assert account is not None
        # Verify FK integrity: user_id points to an existing user
        linked_user = db.get(User, account.user_id)
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
        "app.workers.tasks.start_warming",
        "app.workers.tasks.check_cooldowns",
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
