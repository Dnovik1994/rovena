"""Tests for Admin Warming API endpoints (/api/v1/admin/warming/...)."""

import io
import os
import tempfile
from unittest.mock import patch

from fastapi import status

from app.core.database import SessionLocal
from app.core.security import create_access_token
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.user import User, UserRole


PREFIX = "/api/v1/admin/warming"


# ── Helpers ──────────────────────────────────────────────────────────


def _create_admin() -> User:
    with SessionLocal() as db:
        user = User(
            telegram_id=9000,
            username="warming_admin",
            is_admin=True,
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _create_regular_user() -> User:
    with SessionLocal() as db:
        user = User(
            telegram_id=9001,
            username="warming_user",
            is_admin=False,
            role=UserRole.user,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user


def _admin_headers() -> dict[str, str]:
    admin = _create_admin()
    token = create_access_token(str(admin.id))
    return {"Authorization": f"Bearer {token}"}


def _user_headers() -> dict[str, str]:
    user = _create_regular_user()
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _create_account(owner_id: int, **kwargs) -> TelegramAccount:
    with SessionLocal() as db:
        account = TelegramAccount(
            owner_user_id=owner_id,
            phone_e164=kwargs.get("phone_e164", "+380991234567"),
            status=kwargs.get("status", TelegramAccountStatus.warming),
            warming_day=kwargs.get("warming_day", 0),
            is_trusted=kwargs.get("is_trusted", False),
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return account


# ═══════════════════════════════════════════════════════════════════
# Warming Channels
# ═══════════════════════════════════════════════════════════════════


def test_create_channel(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/channels",
        json={"username": "test_channel", "channel_type": "channel", "language": "uk"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["username"] == "test_channel"
    assert data["channel_type"] == "channel"
    assert data["is_active"] is True


def test_list_channels(client):
    headers = _admin_headers()
    # Create two channels
    client.post(
        f"{PREFIX}/channels",
        json={"username": "ch_a", "channel_type": "channel"},
        headers=headers,
    )
    client.post(
        f"{PREFIX}/channels",
        json={"username": "ch_b", "channel_type": "group"},
        headers=headers,
    )

    resp = client.get(f"{PREFIX}/channels", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert len(data) >= 2
    usernames = [ch["username"] for ch in data]
    assert "ch_a" in usernames
    assert "ch_b" in usernames


def test_delete_channel(client):
    headers = _admin_headers()
    create_resp = client.post(
        f"{PREFIX}/channels",
        json={"username": "to_delete", "channel_type": "channel"},
        headers=headers,
    )
    channel_id = create_resp.json()["id"]

    del_resp = client.delete(f"{PREFIX}/channels/{channel_id}", headers=headers)
    assert del_resp.status_code == status.HTTP_204_NO_CONTENT

    # Verify soft-delete: still in DB but is_active=False
    list_resp = client.get(f"{PREFIX}/channels?is_active=false", headers=headers)
    deleted = [ch for ch in list_resp.json() if ch["id"] == channel_id]
    assert len(deleted) == 1
    assert deleted[0]["is_active"] is False


def test_create_channel_requires_admin(client):
    headers = _user_headers()
    resp = client.post(
        f"{PREFIX}/channels",
        json={"username": "unauth_channel", "channel_type": "channel"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_403_FORBIDDEN


# ═══════════════════════════════════════════════════════════════════
# Warming Bios
# ═══════════════════════════════════════════════════════════════════


def test_create_bio(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/bios",
        json={"text": "Hello warming bio"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["text"] == "Hello warming bio"
    assert data["is_active"] is True


def test_create_bio_max_length(client):
    headers = _admin_headers()
    long_text = "x" * 201
    resp = client.post(
        f"{PREFIX}/bios",
        json={"text": long_text},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_delete_bio(client):
    headers = _admin_headers()
    create_resp = client.post(
        f"{PREFIX}/bios",
        json={"text": "bio to delete"},
        headers=headers,
    )
    bio_id = create_resp.json()["id"]

    del_resp = client.delete(f"{PREFIX}/bios/{bio_id}", headers=headers)
    assert del_resp.status_code == status.HTTP_204_NO_CONTENT

    # Soft delete: should not appear in active list
    list_resp = client.get(f"{PREFIX}/bios", headers=headers)
    active_ids = [b["id"] for b in list_resp.json()]
    assert bio_id not in active_ids


# ═══════════════════════════════════════════════════════════════════
# Warming Photos
# ═══════════════════════════════════════════════════════════════════


def test_upload_photo(client, tmp_path):
    headers = _admin_headers()
    # Create a minimal JPEG-like file content
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100

    with patch(
        "app.api.v1.admin_warming.WARMING_PHOTOS_DIR",
        tmp_path,
    ):
        resp = client.post(
            f"{PREFIX}/photos",
            headers=headers,
            files={"file": ("test.jpg", io.BytesIO(fake_jpeg), "image/jpeg")},
        )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["filename"] == "test.jpg"
    assert data["is_active"] is True


def test_upload_wrong_type(client, tmp_path):
    headers = _admin_headers()

    with patch(
        "app.api.v1.admin_warming.WARMING_PHOTOS_DIR",
        tmp_path,
    ):
        resp = client.post(
            f"{PREFIX}/photos",
            headers=headers,
            files={"file": ("test.txt", io.BytesIO(b"hello"), "text/plain")},
        )
    assert resp.status_code == status.HTTP_400_BAD_REQUEST


def test_delete_photo(client, tmp_path):
    headers = _admin_headers()
    fake_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 100

    with patch(
        "app.api.v1.admin_warming.WARMING_PHOTOS_DIR",
        tmp_path,
    ):
        create_resp = client.post(
            f"{PREFIX}/photos",
            headers=headers,
            files={"file": ("photo.jpg", io.BytesIO(fake_jpeg), "image/jpeg")},
        )
        photo_id = create_resp.json()["id"]
        file_path = create_resp.json()["file_path"]

        # File should exist on disk
        assert os.path.exists(file_path)

        del_resp = client.delete(f"{PREFIX}/photos/{photo_id}", headers=headers)
        assert del_resp.status_code == status.HTTP_204_NO_CONTENT

        # File should be removed from disk
        assert not os.path.exists(file_path)


# ═══════════════════════════════════════════════════════════════════
# Warming Usernames
# ═══════════════════════════════════════════════════════════════════


def test_create_username(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/usernames",
        json={"template": "cool_user_99"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["template"] == "cool_user_99"
    assert data["is_active"] is True


def test_invalid_username_chars(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/usernames",
        json={"template": "Hello World"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_delete_username(client):
    headers = _admin_headers()
    create_resp = client.post(
        f"{PREFIX}/usernames",
        json={"template": "to_del_uname"},
        headers=headers,
    )
    uname_id = create_resp.json()["id"]

    del_resp = client.delete(f"{PREFIX}/usernames/{uname_id}", headers=headers)
    assert del_resp.status_code == status.HTTP_204_NO_CONTENT

    # Soft delete: not in active list
    list_resp = client.get(f"{PREFIX}/usernames", headers=headers)
    active_ids = [u["id"] for u in list_resp.json()]
    assert uname_id not in active_ids


# ═══════════════════════════════════════════════════════════════════
# Warming Names
# ═══════════════════════════════════════════════════════════════════


def test_create_name(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/names",
        json={"first_name": "Olena", "last_name": "Shevchenko"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["first_name"] == "Olena"
    assert data["last_name"] == "Shevchenko"


def test_create_name_no_last(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/names",
        json={"first_name": "Andriy"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["first_name"] == "Andriy"
    assert data["last_name"] is None


# ═══════════════════════════════════════════════════════════════════
# Trusted Accounts
# ═══════════════════════════════════════════════════════════════════


def test_toggle_trusted(client):
    admin = _create_admin()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}
    account = _create_account(admin.id, is_trusted=False)

    resp = client.patch(
        f"{PREFIX}/accounts/{account.id}/trusted",
        json={"is_trusted": True},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_200_OK
    assert resp.json()["is_trusted"] is True


def test_list_trusted(client):
    admin = _create_admin()
    headers = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}

    _create_account(admin.id, phone_e164="+380111111111", is_trusted=True)
    _create_account(admin.id, phone_e164="+380222222222", is_trusted=False)
    _create_account(admin.id, phone_e164="+380333333333", is_trusted=True)

    resp = client.get(f"{PREFIX}/accounts/trusted", headers=headers)
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    # Only trusted accounts
    assert all(a["is_trusted"] for a in data)
    assert len(data) >= 2


# ═══════════════════════════════════════════════════════════════════
# Notification Settings
# ═══════════════════════════════════════════════════════════════════


def test_create_notification_setting(client):
    headers = _admin_headers()
    resp = client.post(
        f"{PREFIX}/notifications",
        json={"chat_id": "-100123456789"},
        headers=headers,
    )
    assert resp.status_code == status.HTTP_201_CREATED
    data = resp.json()
    assert data["chat_id"] == "-100123456789"
    assert data["notify_account_banned"] is True
    assert data["notify_flood_wait"] is True


def test_update_notification_setting(client):
    headers = _admin_headers()
    create_resp = client.post(
        f"{PREFIX}/notifications",
        json={"chat_id": "-100999999"},
        headers=headers,
    )
    notif_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"{PREFIX}/notifications/{notif_id}",
        json={"notify_flood_wait": False},
        headers=headers,
    )
    assert patch_resp.status_code == status.HTTP_200_OK
    assert patch_resp.json()["notify_flood_wait"] is False
    # Other fields unchanged
    assert patch_resp.json()["notify_account_banned"] is True


def test_delete_notification_setting(client):
    headers = _admin_headers()
    create_resp = client.post(
        f"{PREFIX}/notifications",
        json={"chat_id": "-100888888"},
        headers=headers,
    )
    notif_id = create_resp.json()["id"]

    del_resp = client.delete(f"{PREFIX}/notifications/{notif_id}", headers=headers)
    assert del_resp.status_code == status.HTTP_204_NO_CONTENT

    # Should not appear in list anymore (hard delete)
    list_resp = client.get(f"{PREFIX}/notifications", headers=headers)
    ids = [n["id"] for n in list_resp.json()]
    assert notif_id not in ids
