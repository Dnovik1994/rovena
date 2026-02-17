"""Celery tasks for the new InviteCampaign dispatch system."""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import sentry_sdk
from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import FloodWait, PeerFlood, UserAlreadyParticipant, UserPrivacyRestricted

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.models.invite_campaign import InviteCampaign, InviteCampaignStatus
from app.models.invite_task import InviteTask, InviteTaskStatus
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.tg_user import TgUser
from app.workers import celery_app

logger = logging.getLogger(__name__)


async def _run_invite_campaign_dispatch(campaign_id: int) -> None:
    """Core dispatch logic — runs inside asyncio.run()."""

    # --- Phase 1: load campaign primitives -----------------------------------
    with SessionLocal() as db:
        campaign = db.get(InviteCampaign, campaign_id)
        if not campaign:
            logger.warning("invite_dispatch: campaign not found id=%d", campaign_id)
            return
        if campaign.status != InviteCampaignStatus.active:
            logger.info("invite_dispatch: campaign %d not active (status=%s)", campaign_id, campaign.status)
            return

        owner_id = campaign.owner_id
        target_link = campaign.target_link
        max_accounts = campaign.max_accounts
        invites_per_hour = campaign.invites_per_hour_per_account

    # --- Phase 2: pick active accounts for this owner ------------------------
    with SessionLocal() as db:
        accounts = (
            db.query(TelegramAccount)
            .filter(
                TelegramAccount.owner_user_id == owner_id,
                TelegramAccount.status == TelegramAccountStatus.active,
            )
            .order_by(TelegramAccount.id.asc())
            .limit(max_accounts)
            .all()
        )
        account_ids = [a.id for a in accounts]

    if not account_ids:
        logger.warning("invite_dispatch: no active accounts for owner_id=%d campaign=%d", owner_id, campaign_id)
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

        # Fetch pending tasks
        with SessionLocal() as db:
            pending_tasks = (
                db.query(InviteTask)
                .filter(
                    InviteTask.campaign_id == campaign_id,
                    InviteTask.status == InviteTaskStatus.pending,
                )
                .order_by(InviteTask.id.asc())
                .limit(available_slots)
                .all()
            )
            task_ids = [t.id for t in pending_tasks]

        if not task_ids:
            break  # No more pending tasks

        # Build TG client for this account
        with SessionLocal() as db:
            account = db.get(TelegramAccount, acct_id)
            if not account or account.status != TelegramAccountStatus.active:
                continue
            proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
            try:
                client = create_tg_account_client(account, proxy)
            except TelegramClientDisabledError:
                logger.warning("invite_dispatch: TG client disabled account_id=%d", acct_id)
                continue
            except Exception as exc:
                logger.error("invite_dispatch: cannot create TG client account_id=%d: %s", acct_id, exc)
                continue

        # Process tasks with this client
        sleep_interval = 3600 / invites_per_hour
        account_broke = False

        try:
            async with client:
                for task_id in task_ids:
                    if account_broke:
                        break

                    with SessionLocal() as db:
                        task = db.get(InviteTask, task_id)
                        if not task or task.status != InviteTaskStatus.pending:
                            continue

                        tg_user = db.get(TgUser, task.tg_user_id)
                        if not tg_user:
                            task.status = InviteTaskStatus.skipped
                            task.error_message = "tg_user not found"
                            db.commit()
                            continue

                        telegram_id = tg_user.telegram_id

                        task.account_id = acct_id
                        task.status = InviteTaskStatus.in_progress
                        task.attempted_at = datetime.now(timezone.utc)
                        db.commit()

                    # Perform the invite (no DB session held)
                    try:
                        await client.add_chat_members(target_link, [telegram_id])

                        # Success
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.success
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            campaign = db.get(InviteCampaign, campaign_id)
                            if campaign:
                                campaign.invites_completed += 1
                                db.commit()

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
                        break

                    except PeerFlood as exc:
                        sentry_sdk.capture_exception(exc)
                        logger.warning("invite_dispatch: PeerFlood account_id=%d", acct_id)
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.failed
                                task.error_message = "PeerFlood"
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            campaign = db.get(InviteCampaign, campaign_id)
                            if campaign:
                                campaign.invites_failed += 1
                                db.commit()
                        account_broke = True
                        break

                    except UserPrivacyRestricted as exc:
                        sentry_sdk.capture_exception(exc)
                        with SessionLocal() as db:
                            task = db.get(InviteTask, task_id)
                            if task:
                                task.status = InviteTaskStatus.failed
                                task.error_message = "UserPrivacyRestricted"
                                task.completed_at = datetime.now(timezone.utc)
                                db.commit()
                            campaign = db.get(InviteCampaign, campaign_id)
                            if campaign:
                                campaign.invites_failed += 1
                                db.commit()

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
                            campaign = db.get(InviteCampaign, campaign_id)
                            if campaign:
                                campaign.invites_failed += 1
                                db.commit()

                    # Sleep between invites with jitter
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

        if pending_count == 0:
            campaign.status = InviteCampaignStatus.completed
            campaign.completed_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("invite_dispatch: campaign %d completed", campaign_id)
        elif campaign.status == InviteCampaignStatus.active:
            db.commit()
            # Reschedule for next dispatch round
            invite_campaign_dispatch.apply_async(
                args=[campaign_id],
                countdown=60,
            )
            logger.info(
                "invite_dispatch: campaign %d rescheduled, %d pending tasks remain",
                campaign_id, pending_count,
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
        asyncio.run(_run_invite_campaign_dispatch(campaign_id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "invite_campaign_dispatch hit soft time limit | task_id=%s campaign_id=%d",
            self.request.id, campaign_id,
        )
        # Reschedule if still active
        with SessionLocal() as db:
            campaign = db.get(InviteCampaign, campaign_id)
            if campaign and campaign.status == InviteCampaignStatus.active:
                invite_campaign_dispatch.apply_async(
                    args=[campaign_id],
                    countdown=60,
                )
