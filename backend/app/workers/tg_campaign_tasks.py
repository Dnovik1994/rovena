"""Tasks for parsing source group members into contacts."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import FloodWait
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.workers.tg_timeout_helpers import collect_async_gen, safe_call
from app.core.database import SessionLocal
from app.models.contact import Contact
from app.models.proxy import Proxy
from app.models.source import Source
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.workers import celery_app

import sentry_sdk

logger = logging.getLogger(__name__)


async def _run_parse_source_members(
    source_id: int,
    campaign_id: int | None = None,
) -> None:
    """Parse members of a Telegram source group/channel into Contact records.

    Steps:
      1. Load the Source from DB.
      2. Pick an active TelegramAccount from the same project owner.
      3. Join the source group/channel if needed (invite link or username).
      4. Iterate over chat members, upserting Contact records.
      5. Skip bots, deleted accounts, and our own system accounts.
    """
    # --- Phase 1: load source & pick an active TG account ------------------
    with SessionLocal() as db:
        source = db.get(Source, source_id)
        if not source:
            logger.warning("parse_source_members: source not found id=%d", source_id)
            return

        source_link = source.link
        project_id = source.project_id
        owner_id = source.owner_id

        # Pick one active TelegramAccount owned by the same user
        tg_account = (
            db.query(TelegramAccount)
            .filter(
                TelegramAccount.owner_user_id == owner_id,
                TelegramAccount.status == TelegramAccountStatus.active,
            )
            .order_by(TelegramAccount.id.asc())
            .first()
        )
        if not tg_account:
            logger.warning(
                "parse_source_members: no active TelegramAccount for owner_id=%d source_id=%d",
                owner_id, source_id,
            )
            return

        account_id = tg_account.id
        proxy = db.get(Proxy, tg_account.proxy_id) if tg_account.proxy_id else None

        try:
            client = create_tg_account_client(
                tg_account, proxy,
                in_memory=False, workdir="/data/pyrogram_sessions",
            )
        except TelegramClientDisabledError:
            logger.warning("parse_source_members: TG client disabled, account_id=%d", account_id)
            return
        except Exception as exc:
            logger.error("parse_source_members: cannot create TG client account_id=%d: %s", account_id, exc)
            return

    # --- Phase 2: connect, join group, parse members -----------------------
    stats = {"total": 0, "created": 0, "updated": 0, "skipped": 0}

    try:
        async with client:
            # Get our own user id so we can skip ourselves
            me = await asyncio.wait_for(client.get_me(), timeout=15)
            own_user_id = me.id

            # Join the source group/channel and resolve numeric chat_id
            if source_link.startswith("https://t.me/+") or source_link.startswith("https://t.me/joinchat/"):
                # Invite link — join via link, use returned chat id
                try:
                    joined_chat = await safe_call(client.join_chat(source_link), timeout=30)
                    if joined_chat is None:
                        raise TimeoutError("join_chat timed out")
                    chat_identifier = joined_chat.id
                    logger.info(
                        "parse_source_members: joined via invite link source_id=%d chat_id=%s",
                        source_id, chat_identifier,
                    )
                except Exception as exc:
                    logger.info(
                        "parse_source_members: join_chat result for source_id=%d: %s — retrying",
                        source_id, type(exc).__name__,
                    )
                    try:
                        joined_chat = await safe_call(client.join_chat(source_link), timeout=30)
                        if joined_chat is None:
                            raise TimeoutError("join_chat retry timed out")
                        chat_identifier = joined_chat.id
                    except Exception:
                        logger.error(
                            "parse_source_members: cannot resolve invite link source_id=%d",
                            source_id,
                        )
                        return
            else:
                # Public username — extract from link or use as-is
                username = source_link
                if "t.me/" in username:
                    username = username.rstrip("/").split("t.me/")[-1]
                try:
                    joined_chat = await safe_call(client.join_chat(username), timeout=30)
                    if joined_chat is None:
                        raise TimeoutError("join_chat timed out")
                    chat_identifier = joined_chat.id
                    logger.info(
                        "parse_source_members: joined @%s source_id=%d chat_id=%s",
                        username, source_id, chat_identifier,
                    )
                except Exception as exc:
                    logger.info(
                        "parse_source_members: join_chat result for @%s source_id=%d: %s — using username",
                        username, source_id, type(exc).__name__,
                    )
                    chat_identifier = username

            # Parse members
            members = await collect_async_gen(
                client.get_chat_members(chat_identifier), timeout=300, max_items=50_000,
            )
            for member in members:
                user = member.user
                if not user:
                    stats["skipped"] += 1
                    continue

                # Skip bots, deleted accounts, and our own accounts
                if user.is_bot:
                    stats["skipped"] += 1
                    continue
                if user.is_deleted:
                    stats["skipped"] += 1
                    continue
                if user.id == own_user_id:
                    stats["skipped"] += 1
                    continue

                stats["total"] += 1

                # Upsert contact
                with SessionLocal() as db:
                    try:
                        # Try INSERT ... ON DUPLICATE KEY UPDATE (MySQL)
                        stmt = mysql_insert(Contact).values(
                            project_id=project_id,
                            owner_id=owner_id,
                            source_id=source_id,
                            telegram_id=user.id,
                            username=user.username,
                            first_name=user.first_name or "Unknown",
                            last_name=user.last_name,
                            blocked=False,
                        )
                        stmt = stmt.on_duplicate_key_update(
                            username=stmt.inserted.username,
                            first_name=stmt.inserted.first_name,
                            last_name=stmt.inserted.last_name,
                            source_id=stmt.inserted.source_id,
                            blocked=False,
                        )
                        result = db.execute(stmt)
                        db.commit()

                        if result.rowcount == 1:
                            stats["created"] += 1
                        elif result.rowcount == 2:
                            # MySQL returns 2 for ON DUPLICATE KEY UPDATE that changed values
                            stats["updated"] += 1
                        else:
                            stats["updated"] += 1
                    except IntegrityError:
                        db.rollback()
                        # Fallback: try plain update
                        try:
                            existing = (
                                db.query(Contact)
                                .filter(Contact.telegram_id == user.id)
                                .first()
                            )
                            if existing:
                                existing.username = user.username
                                existing.first_name = user.first_name or "Unknown"
                                existing.last_name = user.last_name
                                existing.source_id = source_id
                                existing.blocked = False
                                db.commit()
                                stats["updated"] += 1
                            else:
                                stats["skipped"] += 1
                        except Exception:
                            db.rollback()
                            stats["skipped"] += 1
                    except Exception:
                        db.rollback()
                        stats["skipped"] += 1

    except FloodWait as exc:
        sentry_sdk.capture_exception(exc)
        logger.warning(
            "parse_source_members: FloodWait %ds, setting cooldown for account_id=%d",
            exc.value, account_id,
        )
        with SessionLocal() as db:
            tg_account = db.get(TelegramAccount, account_id)
            if tg_account:
                tg_account.status = TelegramAccountStatus.cooldown
                tg_account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=exc.value)
                db.commit()
    except Exception as exc:
        sentry_sdk.capture_exception(exc)
        logger.exception(
            "parse_source_members: error source_id=%d account_id=%d: %s",
            source_id, account_id, exc,
        )

    logger.info(
        "parse_source_members: done source_id=%d | total=%d created=%d updated=%d skipped=%d",
        source_id, stats["total"], stats["created"], stats["updated"], stats["skipped"],
    )


@celery_app.task(
    bind=True,
    soft_time_limit=1800,
    time_limit=1900,
)
def parse_source_members(self, source_id: int, campaign_id: int | None = None) -> None:
    """Celery task: parse members of a Telegram source group into contacts."""
    logger.info(
        "parse_source_members started | task_id=%s source_id=%d campaign_id=%s",
        self.request.id, source_id, campaign_id,
    )
    try:
        asyncio.run(_run_parse_source_members(source_id, campaign_id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "parse_source_members hit soft time limit | task_id=%s source_id=%d",
            self.request.id, source_id,
        )
