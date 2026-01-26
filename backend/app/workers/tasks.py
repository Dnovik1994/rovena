import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from app.clients.telegram_client import get_client
from app.core.database import SessionLocal
from app.models.account import Account, AccountStatus
from app.models.campaign import Campaign, CampaignStatus
from app.core.limits import increment_daily_invites
from app.core.metrics import campaign_invites_errors_total, campaign_invites_success_total
from app.models.campaign_dispatch_log import CampaignDispatchLog, DispatchErrorType
from app.models.contact import Contact
from app.models.proxy import Proxy
from app.models.target import Target
from app.services.proxy_sync import sync_3proxy
from app.services.proxy_validation import validate_proxy
from app.services.websocket_manager import manager
from app.workers import celery_app
from pyrogram.errors import FloodWait, PeerIdInvalid, UserAlreadyParticipant, UserBlocked, UserPrivacyRestricted
import sentry_sdk

logger = logging.getLogger(__name__)


def _log_dispatch_error(
    db,
    campaign_id: int,
    account_id: int | None,
    contact_id: int | None,
    error_type: DispatchErrorType,
    error_message: str,
) -> None:
    db.add(
        CampaignDispatchLog(
            campaign_id=campaign_id,
            account_id=account_id,
            contact_id=contact_id,
            error=error_message[:255],
            error_type=error_type,
            error_message=error_message[:255],
            timestamp=datetime.now(timezone.utc),
        )
    )
    db.commit()
    campaign_invites_errors_total.labels(error_type=error_type.value).inc()
    manager.broadcast_sync(
        {
            "type": "dispatch_error",
            "campaign_id": campaign_id,
            "account_id": account_id,
            "contact_id": contact_id,
            "error": error_type.value,
        }
    )


def _set_account_cooldown(db, account: Account, seconds: int) -> None:
    account.status = AccountStatus.cooldown
    account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    db.commit()
    manager.broadcast_sync(
        {
            "type": "account_update",
            "account_id": account.id,
            "status": account.status,
            "actions_completed": account.warming_actions_completed,
            "target_actions": account.target_warming_actions,
            "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None,
        }
    )


async def _run_campaign_dispatch(campaign_id: int) -> None:
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        if not campaign:
            logger.info("Campaign not found", extra={"campaign_id": campaign_id})
            return
        if campaign.status != CampaignStatus.active:
            logger.info(
                "Campaign not active",
                extra={"campaign_id": campaign.id, "status": campaign.status},
            )
            return

        contacts_query = (
            db.query(Contact)
            .filter(Contact.project_id == campaign.project_id)
            .filter(Contact.blocked.is_(False))
        )
        if campaign.source_id:
            contacts_query = contacts_query.filter(Contact.source_id == campaign.source_id)
        contacts = contacts_query.order_by(Contact.id.asc()).all()

        accounts = (
            db.query(Account)
            .filter(Account.owner_id == campaign.owner_id)
            .filter(Account.status == AccountStatus.active)
            .order_by(Account.id.asc())
            .all()
        )

        target = db.get(Target, campaign.target_id) if campaign.target_id else None
        if not target:
            _log_dispatch_error(
                db, campaign.id, None, None, DispatchErrorType.other, "Target not found"
            )
            return

        if not contacts or not accounts:
            campaign.progress = 0.0
            db.commit()
            return

        total_contacts = len(contacts)
        success = 0

        for account in accounts:
            proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
            client = get_client(account, proxy)
            try:
                async with client:
                    for contact in contacts:
                        if success >= total_contacts:
                            break
                        try:
                            await client.add_chat_members(target.link, [contact.telegram_id])
                            success += 1
                            campaign.progress = round((success / total_contacts) * 100, 2)
                            db.commit()
                            campaign_invites_success_total.inc()
                            increment_daily_invites(campaign.owner_id)
                            manager.broadcast_sync(
                                {
                                    "type": "campaign_progress",
                                    "campaign_id": campaign.id,
                                    "progress": campaign.progress,
                                    "success": success,
                                }
                            )
                            await asyncio.sleep(random.uniform(40, 120))
                        except FloodWait as exc:
                            sentry_sdk.capture_exception(exc)
                            _set_account_cooldown(db, account, exc.value)
                            _log_dispatch_error(
                                db,
                                campaign.id,
                                account.id,
                                contact.id,
                                DispatchErrorType.flood_wait,
                                f"FloodWait {exc.value}",
                            )
                            break
                        except UserBlocked as exc:
                            sentry_sdk.capture_exception(exc)
                            contact.blocked = True
                            contact.blocked_reason = "UserBlocked"
                            db.commit()
                            manager.broadcast_sync(
                                {
                                    "type": "contact_blocked",
                                    "contact_id": contact.id,
                                    "reason": "UserBlocked",
                                }
                            )
                            _log_dispatch_error(
                                db,
                                campaign.id,
                                account.id,
                                contact.id,
                                DispatchErrorType.user_blocked,
                                str(exc),
                            )
                        except UserPrivacyRestricted as exc:
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db,
                                campaign.id,
                                account.id,
                                contact.id,
                                DispatchErrorType.user_privacy_restricted,
                                str(exc),
                            )
                        except PeerIdInvalid as exc:
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db,
                                campaign.id,
                                account.id,
                                contact.id,
                                DispatchErrorType.peer_id_invalid,
                                str(exc),
                            )
                        except UserAlreadyParticipant as exc:
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db,
                                campaign.id,
                                account.id,
                                contact.id,
                                DispatchErrorType.other,
                                str(exc),
                            )
                        except Exception as exc:  # noqa: BLE001
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db,
                                campaign.id,
                                account.id,
                                contact.id,
                                DispatchErrorType.other,
                                str(exc),
                            )
            except Exception as exc:  # noqa: BLE001
                sentry_sdk.capture_exception(exc)
                _log_dispatch_error(
                    db,
                    campaign.id,
                    account.id,
                    None,
                    DispatchErrorType.other,
                    str(exc),
                )

            if success >= total_contacts:
                break

        if success >= total_contacts:
            campaign.status = CampaignStatus.completed
            campaign.progress = 100.0
        db.commit()


@celery_app.task
def campaign_dispatch(campaign_id: int) -> None:
    asyncio.run(_run_campaign_dispatch(campaign_id))


@celery_app.task

def account_health_check(account_id: int) -> None:
    logger.info("Checking account", extra={"account_id": account_id})


async def perform_low_risk_action(client) -> int:
    actions = [
        client.get_me,
        lambda: client.get_history("telegram", limit=5),
        lambda: client.get_dialogs(limit=3),
    ]
    if random.random() < 0.4:
        actions.append(lambda: client.join_chat("public_test_group"))

    random.shuffle(actions)
    selected = actions[: random.randint(3, min(8, len(actions)))]

    for action in selected:
        await action()
        await asyncio.sleep(random.uniform(60, 300))

    return len(selected)


async def _run_warming_cycle(account_id: int) -> None:
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if not account:
            logger.info("Account not found", extra={"account_id": account_id})
            return

        if account.status != AccountStatus.warming:
            logger.info(
                "Account not in warming status", extra={"account_id": account_id, "status": account.status}
            )
            return

        if not account.warming_started_at:
            account.warming_started_at = datetime.now(timezone.utc)
            db.commit()

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        client = get_client(account, proxy)

        manager.broadcast_sync(
            {
                "type": "account_update",
                "account_id": account.id,
                "status": account.status,
                "actions_completed": account.warming_actions_completed,
                "target_actions": account.target_warming_actions,
                "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None,
            }
        )

        try:
            async with client:
                actions_done = account.warming_actions_completed
                target_actions = account.target_warming_actions or 10
                while actions_done < target_actions:
                    actions_done += await perform_low_risk_action(client)
                    account.warming_actions_completed = actions_done
                    account.last_activity_at = datetime.now(timezone.utc)
                    db.commit()
                    manager.broadcast_sync(
                        {
                            "type": "account_update",
                            "account_id": account.id,
                            "status": account.status,
                            "actions_completed": account.warming_actions_completed,
                            "target_actions": target_actions,
                            "cooldown_until": account.cooldown_until.isoformat()
                            if account.cooldown_until
                            else None,
                        }
                    )

                account.status = AccountStatus.active
                db.commit()
        except FloodWait as exc:
            sentry_sdk.capture_exception(exc)
            logger.info(
                "FloodWait during warming",
                extra={"account_id": account.id, "wait_seconds": exc.value},
            )
            account.status = AccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=exc.value)
            db.commit()
        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            logger.error("Warming error", extra={"error": str(exc), "account_id": account.id})
            account.status = AccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
            db.commit()

        manager.broadcast_sync(
            {
                "type": "account_update",
                "account_id": account.id,
                "status": account.status,
                "actions_completed": account.warming_actions_completed,
                "target_actions": account.target_warming_actions,
                "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None,
            }
        )


@celery_app.task
def start_warming(account_id: int) -> None:
    asyncio.run(_run_warming_cycle(account_id))


@celery_app.task
def perform_warming_action(account_id: int) -> None:
    logger.info("Perform warming action", extra={"account_id": account_id})


@celery_app.task
def check_cooldowns() -> None:
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        accounts = (
            db.query(Account)
            .filter(Account.status == AccountStatus.cooldown)
            .filter(Account.cooldown_until.isnot(None))
            .all()
        )
        for account in accounts:
            if account.cooldown_until and account.cooldown_until <= now:
                account.status = AccountStatus.active
                manager.broadcast_sync(
                    {
                        "type": "account_update",
                        "account_id": account.id,
                        "status": account.status,
                        "actions_completed": account.warming_actions_completed,
                        "target_actions": account.target_warming_actions,
                        "cooldown_until": None,
                    }
                )
        db.commit()


@celery_app.task
def sync_3proxy_config() -> None:
    sync_3proxy()


@celery_app.task
def validate_proxy_task(proxy_id: int) -> None:
    asyncio.run(validate_proxy(proxy_id))
