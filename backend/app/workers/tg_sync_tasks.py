"""Celery task for full account sync: dialogs + group member parsing."""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.enums import ChatMemberStatus, ChatType, UserStatus
from pyrogram.errors import (
    ChannelPrivate,
    ChatAdminRequired,
    FloodWait,
)

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.tg_account_chat import TgAccountChat
from app.models.tg_chat_member import ChatMemberRole, TgChatMember
from app.models.tg_user import TgUser
from app.workers import celery_app

logger = logging.getLogger(__name__)

# Maximum groups to parse members from in a single sync run
_MAX_GROUPS_PER_SYNC = 10

# Batch commit interval for member parsing
_BATCH_COMMIT_SIZE = 100


# ── Helper: map Pyrogram UserStatus → last_online_at ─────────────────

def _resolve_last_online(pyrogram_user) -> datetime | None:
    """Convert Pyrogram UserStatus to an approximate last_online_at datetime."""
    status = getattr(pyrogram_user, "status", None)
    if status is None:
        return None

    now = datetime.now(timezone.utc)

    if status == UserStatus.ONLINE:
        return now
    elif status == UserStatus.RECENTLY:
        return now - timedelta(days=1)
    elif status == UserStatus.LAST_WEEK:
        return now - timedelta(days=7)
    elif status == UserStatus.LAST_MONTH:
        return now - timedelta(days=30)
    elif status == UserStatus.OFFLINE:
        # Pyrogram stores the exact offline date in pyrogram_user.status.date
        # but UserStatus is an enum; the date is on the user object itself
        last_online_date = getattr(pyrogram_user, "last_online_date", None)
        if last_online_date:
            if last_online_date.tzinfo is None:
                return last_online_date.replace(tzinfo=timezone.utc)
            return last_online_date
        return None
    elif status == UserStatus.LONG_AGO:
        return None

    return None


# ── Helper: map Pyrogram ChatMemberStatus → ChatMemberRole ───────────

def _resolve_member_role(pyrogram_member) -> ChatMemberRole:
    """Convert Pyrogram ChatMemberStatus to our ChatMemberRole enum."""
    status = getattr(pyrogram_member, "status", None)

    if status == ChatMemberStatus.OWNER:
        return ChatMemberRole.owner
    elif status == ChatMemberStatus.ADMINISTRATOR:
        return ChatMemberRole.admin
    elif status == ChatMemberStatus.RESTRICTED:
        return ChatMemberRole.restricted
    elif status == ChatMemberStatus.BANNED:
        return ChatMemberRole.banned
    else:
        return ChatMemberRole.member


# ── Helper: upsert TgUser ────────────────────────────────────────────

def upsert_tg_user(db, pyrogram_user) -> TgUser:
    """Upsert a Telegram user. Returns TgUser with id."""
    last_online = _resolve_last_online(pyrogram_user)

    existing = db.query(TgUser).filter(TgUser.telegram_id == pyrogram_user.id).first()
    if existing:
        existing.username = pyrogram_user.username
        existing.first_name = pyrogram_user.first_name
        existing.last_name = pyrogram_user.last_name
        existing.is_premium = getattr(pyrogram_user, "is_premium", False) or False
        existing.is_deleted = pyrogram_user.is_deleted or False
        if last_online:
            existing.last_online_at = last_online
        return existing
    else:
        new_user = TgUser(
            telegram_id=pyrogram_user.id,
            access_hash=getattr(pyrogram_user, "access_hash", None),
            username=pyrogram_user.username,
            first_name=pyrogram_user.first_name,
            last_name=pyrogram_user.last_name,
            is_bot=pyrogram_user.is_bot or False,
            is_deleted=pyrogram_user.is_deleted or False,
            is_premium=getattr(pyrogram_user, "is_premium", False) or False,
            last_online_at=last_online,
        )
        db.add(new_user)
        db.flush()  # get id
        return new_user


# ── Helper: upsert TgChatMember ──────────────────────────────────────

def upsert_chat_member(db, chat_id: int, tg_user_id: int, pyrogram_member) -> TgChatMember:
    """Upsert a chat member record."""
    role = _resolve_member_role(pyrogram_member)

    existing = db.query(TgChatMember).filter(
        TgChatMember.chat_id == chat_id,
        TgChatMember.user_id == tg_user_id,
    ).first()
    if existing:
        existing.role = role
        return existing
    else:
        new_member = TgChatMember(
            chat_id=chat_id,
            user_id=tg_user_id,
            role=role,
        )
        db.add(new_member)
        return new_member


# ── Main sync logic ──────────────────────────────────────────────────

async def _run_sync_account(account_id: int) -> None:
    log = logger.getChild("sync_account")

    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        if not account:
            log.warning("event=sync_account_not_found account_id=%d", account_id)
            return

        if account.status not in (
            TelegramAccountStatus.verified,
            TelegramAccountStatus.active,
        ):
            log.warning(
                "event=sync_account_bad_status account_id=%d status=%s",
                account_id, account.status,
            )
            return

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None

        try:
            client = create_tg_account_client(account, proxy)
        except TelegramClientDisabledError:
            log.warning("event=sync_account_client_disabled account_id=%d", account_id)
            return
        except Exception as exc:
            log.error("event=sync_account_client_error account_id=%d error=%s", account_id, exc)
            return

        # ── PHASE 1: Sync dialogs ────────────────────────────────────
        try:
            async with client:
                chat_count = 0
                async for dialog in client.get_dialogs():
                    chat = dialog.chat
                    if not chat:
                        continue

                    # Skip private chats and saved messages
                    if chat.type == ChatType.PRIVATE:
                        continue
                    if chat.type == ChatType.BOT:
                        continue

                    # Map chat type
                    if chat.type == ChatType.GROUP:
                        chat_type = "group"
                    elif chat.type == ChatType.SUPERGROUP:
                        chat_type = "supergroup"
                    elif chat.type == ChatType.CHANNEL:
                        chat_type = "channel"
                    else:
                        continue

                    # Determine admin/creator status
                    is_creator = False
                    is_admin = False
                    if hasattr(dialog, "top_message") and hasattr(chat, "permissions"):
                        pass  # defaults
                    # Use chat attributes if available
                    if getattr(chat, "is_creator", False):
                        is_creator = True
                        is_admin = True
                    elif getattr(chat, "is_admin", False):
                        is_admin = True

                    # Upsert tg_account_chats
                    existing_chat = db.query(TgAccountChat).filter(
                        TgAccountChat.account_id == account_id,
                        TgAccountChat.chat_id == chat.id,
                    ).first()

                    if existing_chat:
                        existing_chat.title = chat.title
                        existing_chat.username = chat.username
                        existing_chat.members_count = getattr(chat, "members_count", None)
                        existing_chat.is_admin = is_admin
                        existing_chat.updated_at = datetime.now(timezone.utc)
                    else:
                        new_chat = TgAccountChat(
                            account_id=account_id,
                            chat_id=chat.id,
                            title=chat.title,
                            username=chat.username,
                            chat_type=chat_type,
                            members_count=getattr(chat, "members_count", None),
                            is_creator=is_creator,
                            is_admin=is_admin,
                        )
                        db.add(new_chat)

                    db.commit()
                    chat_count += 1
                    await asyncio.sleep(random.uniform(0.5, 1.5))

                log.info(
                    "event=sync_chats_done account_id=%d synced=%d",
                    account_id, chat_count,
                )

                # ── PHASE 2: Parse group members ─────────────────────────
                now = datetime.now(timezone.utc)
                cutoff = now - timedelta(hours=24)

                groups = (
                    db.query(TgAccountChat)
                    .filter(
                        TgAccountChat.account_id == account_id,
                        TgAccountChat.chat_type.in_(["group", "supergroup"]),
                    )
                    .filter(
                        (TgAccountChat.last_parsed_at.is_(None))
                        | (TgAccountChat.last_parsed_at < cutoff)
                    )
                    .order_by(TgAccountChat.members_count.asc())
                    .limit(_MAX_GROUPS_PER_SYNC)
                    .all()
                )

                for account_chat in groups:
                    parsed_count = 0
                    try:
                        async for member in client.get_chat_members(account_chat.chat_id):
                            if not member.user:
                                continue
                            if member.user.is_bot or member.user.is_deleted:
                                continue

                            # Upsert tg_users
                            tg_user = upsert_tg_user(db, member.user)

                            # Upsert tg_chat_members
                            upsert_chat_member(db, account_chat.chat_id, tg_user.id, member)

                            parsed_count += 1

                            # Batch commit every N records
                            if parsed_count % _BATCH_COMMIT_SIZE == 0:
                                db.commit()
                                await asyncio.sleep(random.uniform(0.3, 0.8))

                        db.commit()

                        # Update last_parsed_at
                        account_chat.last_parsed_at = datetime.now(timezone.utc)
                        db.commit()

                    except FloodWait as e:
                        log.warning(
                            "event=sync_floodwait account_id=%d chat_id=%d wait_s=%d",
                            account_id, account_chat.chat_id, e.value,
                        )
                        account.status = TelegramAccountStatus.cooldown
                        account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=e.value)
                        db.commit()
                        return  # abort entire sync

                    except (ChatAdminRequired, ChannelPrivate) as e:
                        log.warning(
                            "event=sync_chat_access_denied account_id=%d chat_id=%d error=%s",
                            account_id, account_chat.chat_id, type(e).__name__,
                        )
                        continue  # skip this group

                    log.info(
                        "event=sync_members_done account_id=%d chat_id=%d parsed=%d",
                        account_id, account_chat.chat_id, parsed_count,
                    )
                    await asyncio.sleep(random.uniform(2, 5))  # pause between groups

        except FloodWait as e:
            log.warning(
                "event=sync_floodwait_dialogs account_id=%d wait_s=%d",
                account_id, e.value,
            )
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=e.value)
            db.commit()

        except Exception as exc:
            log.exception(
                "event=sync_account_error account_id=%d error=%s",
                account_id, str(exc)[:500],
            )


# ── Celery task ──────────────────────────────────────────────────────

@celery_app.task(bind=True, soft_time_limit=3600, time_limit=3700)
def sync_account_data(self, account_id: int) -> None:
    """Full account sync: dialogs + group member parsing."""
    logger.info(
        "event=sync_account_task_started account_id=%d task_id=%s",
        account_id, self.request.id,
    )
    try:
        asyncio.run(_run_sync_account(account_id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "event=sync_account_task_timeout account_id=%d task_id=%s",
            account_id, self.request.id,
        )
        return
    logger.info(
        "event=sync_account_task_finished account_id=%d task_id=%s",
        account_id, self.request.id,
    )
