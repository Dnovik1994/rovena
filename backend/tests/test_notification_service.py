"""Tests for NotificationService: event type filtering, deduplication, message format."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.admin_notification_setting import AdminNotificationSetting
from app.services.notification_service import NotificationService


def _make_setting(**overrides):
    """Build an AdminNotificationSetting with sensible defaults."""
    defaults = {
        "id": 1,
        "chat_id": "123456",
        "notify_account_banned": True,
        "notify_flood_wait": True,
        "notify_warming_failed": True,
        "notify_system_health": True,
        "notify_flood_rate_threshold": True,
        "is_active": True,
    }
    defaults.update(overrides)
    return AdminNotificationSetting(**defaults)


@pytest.fixture()
def service():
    return NotificationService(bot_token="fake-token")


# ── test_send_respects_event_type_settings ──────────────────────────


async def test_send_respects_event_type_settings(db_session, service):
    """If notify_flood_wait=False the service must NOT call Telegram API."""
    setting = _make_setting(notify_flood_wait=False)
    db_session.add(setting)
    db_session.commit()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "app.services.notification_service.get_sync_redis", return_value=None
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_response
        await service.send("flood_wait", "⚠️ FloodWait\n⏱ Ждать: 60 сек")

    mock_post.assert_not_called()


async def test_send_delivers_when_event_enabled(db_session, service):
    """If notify_account_banned=True the service MUST call Telegram API."""
    setting = _make_setting(notify_account_banned=True)
    db_session.add(setting)
    db_session.commit()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    with (
        patch(
            "app.services.notification_service.get_sync_redis", return_value=None
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_response
        await service.send("account_banned", "🚫 Аккаунт забанен")

    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["chat_id"] == "123456"


# ── test_deduplication ──────────────────────────────────────────────


async def test_deduplication(db_session, service):
    """Second call with identical message within 1h must be skipped."""
    setting = _make_setting()
    db_session.add(setting)
    db_session.commit()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    fake_redis = MagicMock()
    # First call: key not found → send; second call: key found → skip
    fake_redis.get = MagicMock(side_effect=[None, b"1"])
    fake_redis.set = MagicMock()

    message = "🚫 Аккаунт забанен\n📱 +380991234567"

    with (
        patch(
            "app.services.notification_service.get_sync_redis",
            return_value=fake_redis,
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_response

        await service.send("account_banned", message)
        await service.send("account_banned", message)

    # Only one actual HTTP call
    assert mock_post.call_count == 1
    # Redis key was set after successful send
    fake_redis.set.assert_called_once()


# ── test_message_format ─────────────────────────────────────────────


async def test_message_format_account_banned(db_session, service):
    """Verify that emoji and required fields appear in the delivered payload."""
    setting = _make_setting()
    db_session.add(setting)
    db_session.commit()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    message = (
        "🚫 Аккаунт забанен\n"
        "📱 +380991234567 (ID: 42)\n"
        "📝 Причина: UserDeactivatedBan\n"
        "🕐 2026-02-21 18:30 UTC"
    )

    with (
        patch(
            "app.services.notification_service.get_sync_redis", return_value=None
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_response
        await service.send("account_banned", message)

    sent_text = mock_post.call_args[1]["json"]["text"]
    assert "🚫" in sent_text
    assert "Аккаунт забанен" in sent_text
    assert "+380991234567" in sent_text
    assert "ID: 42" in sent_text
    assert "UserDeactivatedBan" in sent_text
    assert "2026-02-21 18:30 UTC" in sent_text


async def test_message_format_flood_wait(db_session, service):
    """Verify FloodWait message format."""
    setting = _make_setting()
    db_session.add(setting)
    db_session.commit()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    message = (
        "⚠️ FloodWait\n"
        "📱 +380991234567 (ID: 42)\n"
        "⏱ Ждать: 3600 сек\n"
        "📊 День прогрева: 5/15\n"
        "🕐 2026-02-21 18:30 UTC"
    )

    with (
        patch(
            "app.services.notification_service.get_sync_redis", return_value=None
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_response
        await service.send("flood_wait", message)

    sent_text = mock_post.call_args[1]["json"]["text"]
    assert "⚠️" in sent_text
    assert "FloodWait" in sent_text
    assert "3600 сек" in sent_text
    assert "День прогрева: 5/15" in sent_text


async def test_message_format_system_health(db_session, service):
    """Verify system health message format."""
    setting = _make_setting()
    db_session.add(setting)
    db_session.commit()

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()

    message = (
        "🔴 Система: worker недоступен\n"
        "📝 Причина: No heartbeat for 5 minutes\n"
        "🕐 2026-02-21 18:30 UTC"
    )

    with (
        patch(
            "app.services.notification_service.get_sync_redis", return_value=None
        ),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_response
        await service.send("system_health", message)

    sent_text = mock_post.call_args[1]["json"]["text"]
    assert "🔴" in sent_text
    assert "worker недоступен" in sent_text
    assert "No heartbeat for 5 minutes" in sent_text
