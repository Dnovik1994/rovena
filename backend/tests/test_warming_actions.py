"""Tests for new warming action functions (tg_warming_actions)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.workers.tg_warming_actions import (
    _action_add_contacts,
    _action_go_online,
    _action_set_bio,
    _action_set_name,
    _action_set_photo,
    _action_set_username,
    _action_trusted_conversation,
)


@pytest.fixture()
def tg_client():
    return AsyncMock()


@pytest.fixture()
def account():
    acc = MagicMock()
    acc.id = 1
    acc.phone_e164 = "+380501234567"
    acc.warming_photo_id = None
    return acc


@pytest.fixture()
def db():
    return MagicMock()


# ── _action_set_photo ──────────────────────────────────────────────────


async def test_set_photo_no_free_photos(tg_client, account, db):
    db.query.return_value.filter_by.return_value.first.return_value = None
    result = await _action_set_photo(tg_client, account, db)
    assert result is False
    tg_client.set_profile_photo.assert_not_called()


async def test_set_photo_success(tg_client, account, db):
    photo = MagicMock()
    photo.file_path = "/photos/test.jpg"
    photo.assigned_account_id = None
    db.query.return_value.filter_by.return_value.first.return_value = photo
    tg_client.set_profile_photo = AsyncMock()

    result = await _action_set_photo(tg_client, account, db)

    assert result is True
    assert photo.assigned_account_id == account.id
    assert account.warming_photo_id == photo.id
    tg_client.set_profile_photo.assert_called_once_with(photo="/photos/test.jpg")
    # One commit for the assignment (API succeeded, no rollback commit)
    assert db.commit.call_count == 1


async def test_set_photo_api_error_rollback(tg_client, account, db):
    photo = MagicMock()
    photo.file_path = "/photos/test.jpg"
    photo.assigned_account_id = None
    db.query.return_value.filter_by.return_value.first.return_value = photo
    tg_client.set_profile_photo = AsyncMock(side_effect=Exception("API error"))

    with pytest.raises(Exception, match="API error"):
        await _action_set_photo(tg_client, account, db)

    # Verify rollback
    assert photo.assigned_account_id is None
    assert account.warming_photo_id is None
    # Two commits: assignment + rollback
    assert db.commit.call_count == 2


# ── _action_set_bio ────────────────────────────────────────────────────


async def test_set_bio_from_db(tg_client, account, db):
    bio = MagicMock()
    bio.text = "Test bio"
    db.query.return_value.filter_by.return_value.all.return_value = [bio]
    tg_client.update_profile = AsyncMock()

    result = await _action_set_bio(tg_client, account, db)

    assert result is True
    tg_client.update_profile.assert_called_once_with(bio="Test bio")


async def test_set_bio_fallback(tg_client, account, db):
    db.query.return_value.filter_by.return_value.all.return_value = []
    tg_client.update_profile = AsyncMock()

    with patch("app.workers.tg_warming_actions.random.choice", return_value="🇺🇦"):
        result = await _action_set_bio(tg_client, account, db)

    assert result is True
    tg_client.update_profile.assert_called_once_with(bio="🇺🇦")


# ── _action_set_username ───────────────────────────────────────────────


async def test_set_username_no_templates(tg_client, account, db):
    db.query.return_value.filter_by.return_value.all.return_value = []
    result = await _action_set_username(tg_client, account, db)
    assert result is False


async def test_set_username_success(tg_client, account, db):
    template = MagicMock()
    template.template = "user_test"
    db.query.return_value.filter_by.return_value.all.return_value = [template]
    tg_client.update_username = AsyncMock()

    result = await _action_set_username(tg_client, account, db)

    assert result is True
    tg_client.update_username.assert_called_once()
    call_kwargs = tg_client.update_username.call_args.kwargs
    assert call_kwargs["username"].startswith("user_test_")


async def test_set_username_all_occupied(tg_client, account, db):
    from pyrogram.errors import UsernameOccupied

    template = MagicMock()
    template.template = "user_test"
    db.query.return_value.filter_by.return_value.all.return_value = [template]
    tg_client.update_username = AsyncMock(side_effect=UsernameOccupied())

    result = await _action_set_username(tg_client, account, db)

    assert result is False
    assert tg_client.update_username.call_count == 3


# ── _action_set_name ──────────────────────────────────────────────────


async def test_set_name_no_names(tg_client, account, db):
    db.query.return_value.filter_by.return_value.all.return_value = []
    result = await _action_set_name(tg_client, account, db)
    assert result is False


async def test_set_name_success(tg_client, account, db):
    name = MagicMock()
    name.first_name = "Test"
    name.last_name = "User"
    db.query.return_value.filter_by.return_value.all.return_value = [name]
    tg_client.update_profile = AsyncMock()

    result = await _action_set_name(tg_client, account, db)

    assert result is True
    tg_client.update_profile.assert_called_once_with(
        first_name="Test", last_name="User",
    )


async def test_set_name_no_last_name(tg_client, account, db):
    name = MagicMock()
    name.first_name = "Test"
    name.last_name = None
    db.query.return_value.filter_by.return_value.all.return_value = [name]
    tg_client.update_profile = AsyncMock()

    result = await _action_set_name(tg_client, account, db)

    assert result is True
    tg_client.update_profile.assert_called_once_with(
        first_name="Test", last_name="",
    )


# ── _action_add_contacts ──────────────────────────────────────────────


async def test_add_contacts_no_trusted(tg_client, account, db):
    db.query.return_value.filter.return_value.all.return_value = []
    result = await _action_add_contacts(tg_client, account, db)
    assert result is False


async def test_add_contacts_success(tg_client, account, db):
    trusted1 = MagicMock()
    trusted1.phone_e164 = "+380501111111"
    trusted2 = MagicMock()
    trusted2.phone_e164 = "+380502222222"
    db.query.return_value.filter.return_value.all.return_value = [trusted1, trusted2]
    tg_client.import_contacts = AsyncMock()

    result = await _action_add_contacts(tg_client, account, db)

    assert result is True
    tg_client.import_contacts.assert_called_once()
    contacts = tg_client.import_contacts.call_args[0][0]
    assert len(contacts) == 2


# ── _action_trusted_conversation ──────────────────────────────────────


async def test_trusted_conversation_no_trusted(tg_client, account, db):
    db.query.return_value.filter.return_value.all.return_value = []
    result = await _action_trusted_conversation(tg_client, account, db)
    assert result is False


async def test_trusted_conversation_client_creation_fails(tg_client, account, db):
    trusted = MagicMock()
    trusted.id = 2
    trusted.proxy_id = None
    trusted.phone_e164 = "+380501111111"
    db.query.return_value.filter.return_value.all.return_value = [trusted]

    with patch(
        "app.workers.tg_warming_actions.create_tg_account_client",
        side_effect=Exception("Client creation failed"),
    ):
        result = await _action_trusted_conversation(tg_client, account, db)

    assert result is False


async def test_trusted_conversation_success(tg_client, account, db):
    trusted = MagicMock()
    trusted.id = 2
    trusted.proxy_id = None
    trusted.phone_e164 = "+380501111111"
    db.query.return_value.filter.return_value.all.return_value = [trusted]

    client_trusted = AsyncMock()
    client_trusted.__aenter__ = AsyncMock(return_value=client_trusted)
    client_trusted.__aexit__ = AsyncMock(return_value=False)

    with patch(
        "app.workers.tg_warming_actions.create_tg_account_client",
        return_value=client_trusted,
    ), patch(
        "app.workers.tg_warming_actions.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await _action_trusted_conversation(tg_client, account, db)

    assert result is True
    # Trusted sent at least 1 message
    assert client_trusted.send_message.call_count >= 1
    # New account replied at least 1 message
    assert tg_client.send_message.call_count >= 1


# ── _action_go_online ─────────────────────────────────────────────────


async def test_go_online_success(tg_client, account, db):
    tg_client.get_me = AsyncMock()

    with patch(
        "app.workers.tg_warming_actions.asyncio.sleep",
        new_callable=AsyncMock,
    ):
        result = await _action_go_online(tg_client, account, db)

    assert result is True
    tg_client.get_me.assert_called_once()
