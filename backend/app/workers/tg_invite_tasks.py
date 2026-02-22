"""Celery tasks for the new InviteCampaign dispatch system."""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import sentry_sdk
from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import (
    ChatWriteForbidden,
    FloodWait,
    PeerFlood,
    UserAlreadyParticipant,
    UserBannedInChannel,
    UserPrivacyRestricted,
)
from sqlalchemy import update

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.services.notification_service import send_notification_sync
from app.core.database import SessionLocal
from app.models.invite_campaign import InviteCampaign, InviteCampaignStatus
from app.models.invite_task import InviteTask, InviteTaskStatus
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.tg_user import TgUser
from app.workers import celery_app

logger = logging.getLogger(__name__)

# Maximum seconds a dispatch lease is considered valid
_DISPATCH_LEASE_TTL_SECONDS = 600


def _is_invite_link(link: str) -> bool:
    """Check if the link is a private/public invite link vs plain username."""
    return link.startswith("https://t.me/+") or link.startswith("https://t.me/joinchat/")


def _atomic_increment(db, campaign_id: int, field_name: str) -> None:
    """Atomically increment a counter field on InviteCampaign."""
    field = getattr(InviteCampaign, field_name)
    db.execute(
        update(InviteCampaign)
        .where(InviteCampaign.id == campaign_id)
        .values({field_name: field + 1})
    )
    db.commit()


def _broadcast_invite_progress(campaign_id: int, owner_id: int, db) -> None:
    """Send invite campaign progress via WebSocket."""
    campaign = db.get(InviteCampaign, campaign_id)
    if not campaign:
        return
    total = db.query(InviteTask).filter(InviteTask.campaign_id == campaign_id).count()
    from app.services.websocket_manager import manager

    manager.broadcast_sync({
        "type": "invite_campaign_progress",
        "user_id": owner_id,
        "campaign_id": campaign_id,
        "invites_completed": campaign.invites_completed,
        "invites_failed": campaign.invites_failed,
        "total_tasks": total,
        "status": campaign.status.value,
    })


def _broadcast_invite_error(campaign_id: int, owner_id: int, account_id: int, error_type: str) -> None:
    """Send invite campaign error via WebSocket."""
    from app.services.websocket_manager import manager

    manager.broadcast_sync({
        "type": "invite_campaign_error",
        "user_id": owner_id,
        "campaign_id": campaign_id,
        "account_id": account_id,
        "error_type": error_type,
    })


def _broadcast_invite_completed(campaign_id: int, owner_id: int, db) -> None:
    """Send invite campaign completed via WebSocket."""
    campaign = db.get(InviteCampaign, campaign_id)
    if not campaign:
        return
    from app.services.websocket_manager import manager

    manager.broadcast_sync({
        "type": "invite_campaign_completed",
        "user_id": owner_id,
        "campaign_id": campaign_id,
        "invites_completed": campaign.invites_completed,
        "invites_failed": campaign.invites_failed,
        "status": "completed",
    })


async def _resolve_target_chat_id(client, target_link: str) -> int:
    """Resolve target_link to a numeric chat_id.

    Handles both invite links (https://t.me/+xxx) and usernames.
    The calling account joins the target chat first (idempotent).
    """
    if _is_invite_link(target_link):
        chat = await asyncio.wait_for(client.join_chat(target_link), timeout=10)
        return chat.id

    # Public username — strip URL prefix if present
    username = target_link
    if "t.me/" in username:
        username = username.rstrip("/").split("t.me/")[-1]
    username = username.lstrip("@")

    try:
        chat = await asyncio.wait_for(client.join_chat(username), timeout=10)
        return chat.id
    except UserAlreadyParticipant:
        chat = await asyncio.wait_for(client.get_chat(username), timeout=10)
        return chat.id


async def _run_invite_campaign_dispatch(campaign_id: int, task_id: str | None = None) -> None:
    """Core dispatch logic — runs inside asyncio.run()."""

    now = datetime.now(timezone.utc)

    # --- Phase 0: acquire dispatch lease (prevent parallel runs) -------------
    with SessionLocal() as db:
        campaign = db.get(InviteCampaign, campaign_id)
        if not campaign:
            logger.warning("invite_dispatch: campaign not found id=%d", campaign_id)
            return

        # Check if another dispatch is already running
        if (
            campaign.dispatch_task_id
            and campaign.dispatch_task_id != task_id
            and campaign.dispatch_started_at
            and (now - campaign.dispatch_started_at).total_seconds() < _DISPATCH_LEASE_TTL_SECONDS
        ):
            logger.info(
                "invite_dispatch: another dispatch running for campaign %d (task_id=%s)",
                campaign_id, campaign.dispatch_task_id,
            )
            return

        # Acquire lease
        campaign.dispatch_task_id = task_id
        campaign.dispatch_started_at = now
        db.commit()

    # --- Phase 1: load campaign primitives -----------------------------------
    try:
        await _run_invite_campaign_dispatch_inner(campaign_id)
    finally:
        # --- Release dispatch lease ---
        with SessionLocal() as db:
            campaign = db.get(InviteCampaign, campaign_id)
            if campaign and campaign.dispatch_task_id == task_id:
                campaign.dispatch_task_id = None
                campaign.dispatch_started_at = None
                db.commit()


async def _run_invite_campaign_dispatch_inner(campaign_id: int) -> None:
    """Inner dispatch logic, called after lease is acquired."""

    with SessionLocal() as db:
        campaign = db.get(InviteCampaign, campaign_id)
        if not campaign:
            return
        if campaign.status != InviteCampaignStatus.active:
            logger.info("invite_dispatch: campaign %d not active (status=%s)", campaign_id, campaign.status)
            return

        owner_id = campaign.owner_id
        campaign_name = campaign.name
        target_link = campaign.target_link
        campaign_target_chat_id = campaign.target_chat_id
        max_accounts = campaign.max_accounts
        invites_per_hour = campaign.invites_per_hour_per_account

    # --- Phase 2: pick active accounts for this owner ------------------------
    with SessionLocal() as db:
        accounts = (
            db.query(TelegramAccount)
            .filter(
                TelegramAccount.owner_user_id == owner_id,
                TelegramAccount.status == TelegramAccountStatus.active,
                TelegramAccount.warming_day >= 15,  # only fully warmed-up accounts
            )
            .order_by(TelegramAccount.id.asc())
            .limit(max_accounts)
            .all()
        )
        account_ids = [a.id for a in accounts]

    if not account_ids:
        now = datetime.now(timezone.utc)
        with SessionLocal() as db:
            cooldown_accounts = (
                db.query(TelegramAccount)
                .filter(
                    TelegramAccount.owner_user_id == owner_id,
                    TelegramAccount.status == TelegramAccountStatus.cooldown,
                    TelegramAccount.cooldown_until > now,
                )
                .all()
            )
            if cooldown_accounts:
                min_cooldown = min(a.cooldown_until for a in cooldown_accounts)
                # Ensure timezone-aware comparison (SQLite returns naive datetimes)
                if min_cooldown.tzinfo is None:
                    min_cooldown = min_cooldown.replace(tzinfo=timezone.utc)
                delay_seconds = int((min_cooldown - now).total_seconds()) + 60
                logger.warning(
                    "invite_dispatch: no active accounts for campaign=%d, "
                    "%d account(s) in cooldown; rescheduling in %ds",
                    campaign_id, len(cooldown_accounts), delay_seconds,
                )
                invite_campaign_dispatch.apply_async(
                    args=[campaign_id],
                    countdown=delay_seconds,
                )
            else:
                logger.warning(
                    "invite_dispatch: No warmed-up accounts available "
                    "(status=active, warming_day>=15) "
                    "for owner_id=%d campaign=%d — marking as error",
                    owner_id, campaign_id,
                )
                campaign = db.get(InviteCampaign, campaign_id)
                if campaign:
                    campaign.status = InviteCampaignStatus.error
                    db.commit()
                    send_notification_sync("warming_failed",
                        f"⚠️ Кампания остановлена\n"
                        f"📋 {campaign.name} (ID: {campaign.id})\n"
                        f"📝 Нет прогретых аккаунтов\n"
                        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        return

    # --- Phase 3: process each account ---------------------------------------
    for acct_id in account_ids:
        # Re-check campaign status before each account
        with SessionLocal() as db:
            campaign = db.get(InviteCampaign, campaign_id)
            if not campaign or campaign.status != InviteCampaignStatus.active:
                return

        # Check rate limit for this account
        with SessionLocal() as db:
            one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
            invites_this_hour = (
                db.query(InviteTask)
                .filter(
                    InviteTask.account_id == acct_id,
                    InviteTask.status == InviteTaskStatus.success,
                    InviteTask.completed_at > one_hour_ago,
                )
                .count()
            )

        if invites_this_hour >= invites_per_hour:
            logger.info(
                "invite_dispatch: account %d hit hourly limit (%d/%d)",
                acct_id, invites_this_hour, invites_per_hour,
            )
            continue

        available_slots = invites_per_hour - invites_this_hour

        # Limit batch to 1-3 contacts per dispatch so that the task
        # finishes well within the soft_time_limit even at slow rates.
        batch_size = min(3, available_slots)

        # Fetch pending tasks atomically with SELECT FOR UPDATE SKIP LOCKED
        with SessionLocal() as db:
            pending_tasks = (
                db.query(InviteTask)
                .filter(
                    InviteTask.campaign_id == campaign_id,
                    InviteTask.status == InviteTaskStatus.pending,
                )
                .order_by(InviteTask.id.asc())
                .limit(batch_size)
                .with_for_update(skip_locked=True)
                .all()
            )

            # Immediately mark as in_progress to prevent race conditions
            task_data = []
            for t in pending_tasks:
                t.status = InviteTaskStatus.in_progress
                t.account_id = acct_id
                t.attempted_at = datetime.now(timezone.utc)
                task_data.append({"task_id": t.id, "tg_user_id": t.tg_user_id})
            db.commit()

        if not task_data:
            break  # No more pending tasks

        # Preload telegram_ids for all tasks
        tg_user_map: dict[int, int] = {}
        with SessionLocal() as db:
            tg_user_ids = [td["tg_user_id"] for td in task_data]
            tg_users = db.query(TgUser).filter(TgUser.id.in_(tg_user_ids)).all()
            tg_user_map = {u.id: u.telegram_id for u in tg_users}

        # Build TG client for this account
        with SessionLocal() as db:
            account = db.get(TelegramAccount, acct_id)
            if not account or account.status != TelegramAccountStatus.active:
                # Revert tasks to pending
                for td in task_data:
                    task = db.get(InviteTask, td["task_id"])
                    if task:
                        task.status = InviteTaskStatus.pending
                        task.account_id = None
                db.commit()
                continue
            proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
            try:
                client = create_tg_account_client(
                    account, proxy, in_memory=False, workdir="/data/pyrogram_sessions",
                )
            except TelegramClientDisabledError:
                logger.warning("invite_dispatch: TG client disabled account_id=%d", acct_id)
                for td in task_data:
                    task = db.get(InviteTask, td["task_id"])
                    if task:
                        task.status = InviteTaskStatus.pending
                        task.account_id = None
                db.commit()
                continue
            except Exception as exc:
                logger.error("invite_dispatch: cannot create TG client account_id=%d: %s", acct_id, exc)
                for td in task_data:
                    task = db.get(InviteTask, td["task_id"])
                    if task:
                        task.status = InviteTaskStatus.pending
                        task.account_id = None
                db.commit()
                continue

        # Process tasks with this client
        sleep_interval = 3600 / invites_per_hour
        account_broke = False

        try:
            async with client:
                # Resolve target: use target_chat_id directly, or resolve target_link
                if campaign_target_chat_id is not None:
                    target_chat_id = campaign_target_chat_id
                elif target_link:
                    try:
                        target_chat_id = await _resolve_target_chat_id(client, target_link)
                    except Exception as exc:
                        logger.error(
                            "invite_dispatch: cannot resolve target_link=%s account_id=%d: %s",
                            target_link, acct_id, exc,
                        )
                        sentry_sdk.capture_exception(exc)
                        # Revert tasks to pending
                        with SessionLocal() as db:
                            for td in task_data:
                                task = db.get(InviteTask, td["task_id"])
                                if task:
                                    task.status = InviteTaskStatus.pending
                                    task.account_id = None
                            db.commit()
                        continue
                else:
                    logger.error("invite_dispatch: no target_chat_id or target_link for campaign=%d", campaign_id)
                    with SessionLocal() as db:
                        for td in task_data:
                            task = db.get(InviteTask, td["task_id"])
                            if task:
                                task.status = InviteTaskStatus.pending
                                task.account_id = None
                        db.commit()
                    continue

                for td in task_data:
                    if account_broke:
                        # Revert remaining tasks to pending
                        with SessionLocal() as db:
                            task = db.get(InviteTask, td["task_id"])
                            if task and task.status == InviteTaskStatus.in_progress:
                                task.status = InviteTaskStatus.pending
                                task.account_id = None
                            db.commit()
                        continue

                    task_id = td["task_id"]
                    telegram_id = tg_user_map.get(td["tg_user_id"])

                    if not telegram_id:
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.skipped
                                task.error_message = "tg_user not found"
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                        continue

                    # Resolve user peer cache before invite
                    try:
                        await asyncio.wait_for(client.get_users(telegram_id), timeout=5)
                    except Exception:
                        pass  # If unresolvable — add_chat_members will raise

                    # Perform the invite (no DB session held)
                    try:
                        await asyncio.wait_for(
                            client.add_chat_members(target_chat_id, [telegram_id]),
                            timeout=30,
                        )

                        # Success
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.success
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            _atomic_increment(db, campaign_id, "invites_completed")
                            _broadcast_invite_progress(campaign_id, owner_id, db)

                    except UserAlreadyParticipant:
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.skipped
                                task.error_message = "UserAlreadyParticipant"
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()

                    except FloodWait as exc:
                        sentry_sdk.capture_exception(exc)
                        logger.warning(
                            "invite_dispatch: FloodWait %ds account_id=%d campaign=%d",
                            exc.value, acct_id, campaign_id,
                        )
                        # Revert task to pending
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.pending
                                task.account_id = None
                                db.commit()
                            # Set account cooldown
                            account = db.get(TelegramAccount, acct_id)
                            if account:
                                account.status = TelegramAccountStatus.cooldown
                                account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=exc.value)
                                db.commit()
                        account_broke = True
                        _broadcast_invite_error(campaign_id, owner_id, acct_id, "FloodWait")

                    except PeerFlood as exc:
                        sentry_sdk.capture_exception(exc)
                        logger.warning("invite_dispatch: PeerFlood account_id=%d", acct_id)
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.pending
                                task.account_id = None
                                db.commit()
                            # Set account cooldown (same pattern as FloodWait)
                            account = db.get(TelegramAccount, acct_id)
                            if account:
                                account.status = TelegramAccountStatus.cooldown
                                account.cooldown_until = datetime.now(timezone.utc) + timedelta(minutes=30)
                                db.commit()
                        account_broke = True
                        _broadcast_invite_error(campaign_id, owner_id, acct_id, "PeerFlood")

                    except UserPrivacyRestricted as exc:
                        sentry_sdk.capture_exception(exc)
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.failed
                                task.error_message = "UserPrivacyRestricted"
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            _atomic_increment(db, campaign_id, "invites_failed")

                    except (UserBannedInChannel, ChatWriteForbidden) as exc:
                        sentry_sdk.capture_exception(exc)
                        error_name = type(exc).__name__
                        logger.warning(
                            "invite_dispatch: %s account_id=%d campaign=%d",
                            error_name, acct_id, campaign_id,
                        )
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.failed
                                task.error_message = error_name
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            _atomic_increment(db, campaign_id, "invites_failed")
                            # Mark account as cooldown — banned in target chat
                            account = db.get(TelegramAccount, acct_id)
                            if account:
                                account.status = TelegramAccountStatus.cooldown
                                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=24)
                                account.last_error = f"Banned in target: {error_name}"
                                db.commit()
                        account_broke = True
                        _broadcast_invite_error(campaign_id, owner_id, acct_id, error_name)
                        send_notification_sync("account_banned",
                            f"🚫 Аккаунт забанен в чате\n"
                            f"📱 Account ID: {acct_id}\n"
                            f"📋 Кампания: {campaign_name}\n"
                            f"📝 {error_name}\n"
                            f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")

                    except Exception as exc:  # noqa: BLE001
                        sentry_sdk.capture_exception(exc)
                        logger.error(
                            "invite_dispatch: unexpected error task=%d: %s",
                            task_id, str(exc)[:200],
                        )
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.failed
                                task.error_message = str(exc)[:500]
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            _atomic_increment(db, campaign_id, "invites_failed")

                    # Sleep between invites with jitter
                    if not account_broke:
                        jitter = random.uniform(0.9, 1.3)
                        await asyncio.sleep(sleep_interval * jitter)

        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            logger.exception("invite_dispatch: client error account=%d campaign=%d: %s", acct_id, campaign_id, exc)

    # --- Phase 4: check remaining and reschedule or complete -----------------
    with SessionLocal() as db:
        campaign = db.get(InviteCampaign, campaign_id)
        if not campaign:
            return

        pending_count = (
            db.query(InviteTask)
            .filter(
                InviteTask.campaign_id == campaign_id,
                InviteTask.status == InviteTaskStatus.pending,
            )
            .count()
        )

        in_progress_count = (
            db.query(InviteTask)
            .filter(
                InviteTask.campaign_id == campaign_id,
                InviteTask.status == InviteTaskStatus.in_progress,
            )
            .count()
        )

        if pending_count == 0 and in_progress_count == 0:
            campaign.status = InviteCampaignStatus.completed
            campaign.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("invite_dispatch: campaign %d completed", campaign_id)
            _broadcast_invite_completed(campaign_id, owner_id, db)
            send_notification_sync("warming_completed",
                f"✅ Кампания завершена\n"
                f"📋 {campaign.name} (ID: {campaign.id})\n"
                f"👥 Успешно: {campaign.invites_completed}\n"
                f"❌ Ошибок: {campaign.invites_failed}\n"
                f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        elif campaign.status == InviteCampaignStatus.active:
            db.commit()
            # Reschedule for next dispatch round using the rate-based
            # interval so we don't re-enter faster than the invite rate.
            reschedule_countdown = max(int(3600 / invites_per_hour), 60)
            invite_campaign_dispatch.apply_async(
                args=[campaign_id],
                countdown=reschedule_countdown,
            )
            logger.info(
                "invite_dispatch: campaign %d rescheduled in %ds, %d pending / %d in_progress tasks remain",
                campaign_id, reschedule_countdown, pending_count, in_progress_count,
            )


@celery_app.task(
    bind=True,
    soft_time_limit=300,
    time_limit=330,
)
def invite_campaign_dispatch(self, campaign_id: int) -> None:
    """Celery entry point for invite campaign dispatch."""
    logger.info(
        "invite_campaign_dispatch started | task_id=%s campaign_id=%d",
        self.request.id, campaign_id,
    )
    try:
        asyncio.run(_run_invite_campaign_dispatch(campaign_id, task_id=self.request.id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "invite_campaign_dispatch hit soft time limit | task_id=%s campaign_id=%d",
            self.request.id, campaign_id,
        )
        # Release dispatch lease on timeout
        with SessionLocal() as db:
            campaign = db.get(InviteCampaign, campaign_id)
            if campaign:
                if campaign.dispatch_task_id == self.request.id:
                    campaign.dispatch_task_id = None
                    campaign.dispatch_started_at = None
                if campaign.status == InviteCampaignStatus.active:
                    db.commit()
                    invite_campaign_dispatch.apply_async(
                        args=[campaign_id],
                        countdown=60,
                    )
                else:
                    db.commit()


@celery_app.task(soft_time_limit=60, time_limit=90)
def cleanup_orphan_invite_tasks():
    """Reset stuck in_progress invite tasks back to pending."""
    with SessionLocal() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=15)
        orphans = (
            db.query(InviteTask)
            .filter(
                InviteTask.status == InviteTaskStatus.in_progress,
                InviteTask.attempted_at < cutoff,
            )
            .all()
        )

        for task in orphans:
            task.status = InviteTaskStatus.pending
            task.account_id = None
            task.attempted_at = None

        if orphans:
            db.commit()
            logger.warning("Cleaned up %d orphan invite tasks", len(orphans))
