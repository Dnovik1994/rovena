"""New warming actions for TelegramAccount warming cycle.

These functions are called via _safe_action() wrapper from the warming
cycle.  FloodWait exceptions are NOT caught — they propagate to the
caller so the account enters cooldown.

Each function signature: (client, account, db) -> bool
"""

import asyncio
import logging
import random

from pyrogram.errors import UsernameNotModified, UsernameOccupied
from pyrogram.types import InputPhoneContact

from app.clients.telegram_client import create_tg_account_client
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.warming_bio import WarmingBio
from app.models.warming_name import WarmingName
from app.models.warming_photo import WarmingPhoto
from app.models.warming_username import WarmingUsername

logger = logging.getLogger(__name__)


async def _action_set_photo(client, account, db) -> bool:
    """Set profile photo from the warming photo library.

    Assigns a free WarmingPhoto to the account and sets it as the profile
    photo.  Rolls back the assignment if the Telegram API call fails.
    """
    photo = (
        db.query(WarmingPhoto)
        .filter_by(is_active=True, assigned_account_id=None)
        .first()
    )
    if not photo:
        logger.warning("No free warming photos available for account %s", account.id)
        return False

    photo.assigned_account_id = account.id
    account.warming_photo_id = photo.id
    db.commit()

    try:
        await client.set_profile_photo(photo=photo.file_path)
    except Exception:
        photo.assigned_account_id = None
        account.warming_photo_id = None
        db.commit()
        raise

    return True


async def _action_set_bio(client, account, db) -> bool:
    """Set bio from the warming bio library or a fallback list."""
    bios = db.query(WarmingBio).filter_by(is_active=True).all()
    if bios:
        text = random.choice(bios).text
    else:
        text = random.choice(["", "🇺🇦", "Life is good ✨"])

    await client.update_profile(bio=text)
    return True


async def _action_set_username(client, account, db) -> bool:
    """Set username from the warming username library.

    Appends random digits to a template and retries up to 3 times if the
    username is already taken.
    """
    usernames = db.query(WarmingUsername).filter_by(is_active=True).all()
    if not usernames:
        logger.warning("No warming usernames available for account %s", account.id)
        return False

    template = random.choice(usernames).template

    for _ in range(3):
        username = f"{template}_{random.randint(100, 9999)}"
        try:
            await client.update_username(username=username)
            return True
        except (UsernameOccupied, UsernameNotModified):
            continue

    return False


async def _action_set_name(client, account, db) -> bool:
    """Set first/last name from the warming name library."""
    names = db.query(WarmingName).filter_by(is_active=True).all()
    if not names:
        logger.warning("No warming names available for account %s", account.id)
        return False

    name = random.choice(names)
    await client.update_profile(first_name=name.first_name, last_name=name.last_name or "")
    return True


async def _action_add_contacts(client, account, db) -> bool:
    """Import 2-3 trusted accounts as contacts."""
    trusted_accounts = (
        db.query(TelegramAccount)
        .filter(
            TelegramAccount.is_trusted == True,  # noqa: E712
            TelegramAccount.status == TelegramAccountStatus.active,
        )
        .all()
    )
    if len(trusted_accounts) < 1:
        logger.warning(
            "No trusted accounts available for adding contacts (account %s)",
            account.id,
        )
        return False

    count = min(random.randint(2, 3), len(trusted_accounts))
    selected = random.sample(trusted_accounts, count)

    contacts = [
        InputPhoneContact(phone=trusted.phone_e164, first_name=f"Contact_{i}")
        for i, trusted in enumerate(selected)
    ]
    await client.import_contacts(contacts)
    return True


async def _action_trusted_conversation(client, account, db) -> bool:
    """Simulate a conversation between the account and a trusted account.

    Creates a separate Pyrogram client for a random trusted account.
    Both clients exchange 1-2 messages with realistic delays.
    """
    trusted_accounts = (
        db.query(TelegramAccount)
        .filter(
            TelegramAccount.is_trusted == True,  # noqa: E712
            TelegramAccount.status == TelegramAccountStatus.active,
        )
        .all()
    )
    if not trusted_accounts:
        return False

    trusted = random.choice(trusted_accounts)
    proxy = db.get(Proxy, trusted.proxy_id) if trusted.proxy_id else None

    try:
        client_trusted = create_tg_account_client(
            trusted, proxy, phone=trusted.phone_e164,
            in_memory=False, workdir="/data/pyrogram_sessions",
        )
    except Exception as exc:
        logger.warning(
            "Failed to create client for trusted account %s: %s", trusted.id, exc,
        )
        return False

    async with client_trusted:
        # Step 1: Trusted sends 1-2 messages to the new account
        num_messages = random.randint(1, 2)
        phrases = ["Привет!", "Как дела?", "Привет, как ты?", "Добрый день!"]
        await client_trusted.send_message(account.phone_e164, random.choice(phrases))
        await asyncio.sleep(random.uniform(20, 40))

        # Step 2: Second message from trusted (if chosen)
        if num_messages == 2:
            phrases2 = ["Давно не общались", "Что нового?", "Как жизнь?"]
            await client_trusted.send_message(account.phone_e164, random.choice(phrases2))
            await asyncio.sleep(random.uniform(15, 30))

        # Step 3: New account replies 1-2 messages
        num_replies = random.randint(1, 2)
        replies = ["Привет! 👋", "Всё хорошо!", "Нормально, а ты?", "Привет, рад слышать!"]
        await client.send_message(trusted.phone_e164, random.choice(replies))
        await asyncio.sleep(random.uniform(20, 40))

        if num_replies == 2:
            await client.send_message(trusted.phone_e164, random.choice(replies))
            await asyncio.sleep(random.uniform(20, 40))

    return True


async def _action_go_online(client, account, db) -> bool:
    """Appear online for 1-3 minutes."""
    await client.get_me()
    await asyncio.sleep(random.uniform(60, 180))
    return True
