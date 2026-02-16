import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

from app.core.tz import is_expired

from celery import current_task
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy.exc import IntegrityError

from app.clients.telegram_client import TelegramClientDisabledError, get_client
from app.core.database import SessionLocal
# TODO: заменить Account на TelegramAccount для поддержки per-account api_id
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


def _serialize_status(status) -> str:
    """Safely serialize enum status for JSON."""
    return status.value if hasattr(status, 'value') else str(status)


def _log_task_started(campaign_id: int | None = None, account_id: int | None = None) -> None:
    task = current_task
    task_name = task.name if task else "unknown"
    logger.info(
        "Task %s started | campaign_id=%s | account_id=%s",
        task_name,
        campaign_id,
        account_id,
    )


def _log_dispatch_error(
    db,
    campaign_id: int,
    account_id: int | None,
    contact_id: int | None,
    error_type: DispatchErrorType,
    error_message: str,
    owner_id: int | None = None,
) -> None:
    try:
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
    except IntegrityError:
        db.rollback()
        logger.warning(
            "Failed to log dispatch error: FK violation for campaign=%s account=%s contact=%s",
            campaign_id, account_id, contact_id,
        )
    except Exception as exc:
        db.rollback()
        logger.exception("Failed to log dispatch error: %s", exc)
    campaign_invites_errors_total.labels(error_type=error_type.value).inc()
    manager.broadcast_sync(
        {
            "type": "dispatch_error",
            "user_id": owner_id,
            "campaign_id": campaign_id,
            "account_id": account_id,
            "contact_id": contact_id,
            "error": error_type.value,
        }
    )


# TODO: заменить Account на TelegramAccount для поддержки per-account api_id
def _set_account_cooldown(db, account: Account, seconds: int) -> None:
    account.status = AccountStatus.cooldown
    account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    db.commit()
    manager.broadcast_sync(
        {
            "type": "account_update",
            "user_id": account.owner_id,
            "account_id": account.id,
            "status": _serialize_status(account.status),
            "actions_completed": account.warming_actions_completed,
            "target_actions": account.target_warming_actions,
            "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None,
        }
    )


async def _run_campaign_dispatch(campaign_id: int) -> None:
    # --- Phase 1: load IDs / primitives in a short-lived session ----------
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
        contact_ids = [c.id for c in contacts_query.order_by(Contact.id.asc()).all()]

        # TODO: заменить Account на TelegramAccount для поддержки per-account api_id
        account_ids = [
            a.id
            for a in db.query(Account)
            .filter(Account.owner_id == campaign.owner_id)
            .filter(Account.status == AccountStatus.active)
            .order_by(Account.id.asc())
            .all()
        ]

        target = db.get(Target, campaign.target_id) if campaign.target_id else None
        if not target:
            _log_dispatch_error(
                db, campaign.id, None, None, DispatchErrorType.other, "Target not found",
                owner_id=campaign.owner_id,
            )
            return

        target_link = target.link
        owner_id = campaign.owner_id

        if not contact_ids or not account_ids:
            campaign.progress = 0.0
            db.commit()
            return

    # --- Phase 2: iterate with per-operation sessions ---------------------
    total_contacts = len(contact_ids)
    success = 0

    for acct_id in account_ids:
        # Load account & proxy in a short-lived session, build client
        with SessionLocal() as db:
            account = db.get(Account, acct_id)
            if not account or account.status != AccountStatus.active:
                continue
            proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
            try:
                client = get_client(account, proxy)
            except TelegramClientDisabledError as exc:
                _log_dispatch_error(
                    db, campaign_id, account.id, None,
                    DispatchErrorType.other, str(exc), owner_id=owner_id,
                )
                continue
            except RuntimeError as e:
                logger.error(f"Cannot create Telegram client: {e}")
                account.status = AccountStatus.error
                account.last_error = str(e)
                db.commit()
                _log_dispatch_error(
                    db, campaign_id, account.id, None,
                    DispatchErrorType.other, str(e), owner_id=owner_id,
                )
                continue

        try:
            async with client:
                for contact_id in contact_ids:
                    if success >= total_contacts:
                        break

                    should_sleep = False
                    should_break = False

                    # One short-lived session per contact
                    with SessionLocal() as db:
                        campaign = db.get(Campaign, campaign_id)
                        contact = db.get(Contact, contact_id)
                        account = db.get(Account, acct_id)
                        if not campaign or not contact:
                            continue
                        try:
                            await client.add_chat_members(target_link, [contact.telegram_id])
                            success += 1
                            campaign.progress = round((success / total_contacts) * 100, 2)
                            db.commit()
                            campaign_invites_success_total.inc()
                            increment_daily_invites(owner_id)
                            manager.broadcast_sync(
                                {
                                    "type": "campaign_progress",
                                    "user_id": owner_id,
                                    "campaign_id": campaign_id,
                                    "progress": campaign.progress,
                                    "success": success,
                                }
                            )
                            should_sleep = True
                        except FloodWait as exc:
                            sentry_sdk.capture_exception(exc)
                            if account:
                                _set_account_cooldown(db, account, exc.value)
                            _log_dispatch_error(
                                db, campaign_id, acct_id, contact.id,
                                DispatchErrorType.flood_wait,
                                f"FloodWait {exc.value}",
                                owner_id=owner_id,
                            )
                            should_break = True
                        except UserBlocked as exc:
                            sentry_sdk.capture_exception(exc)
                            contact.blocked = True
                            contact.blocked_reason = "UserBlocked"
                            db.commit()
                            manager.broadcast_sync(
                                {
                                    "type": "contact_blocked",
                                    "user_id": owner_id,
                                    "contact_id": contact.id,
                                    "reason": "UserBlocked",
                                }
                            )
                            _log_dispatch_error(
                                db, campaign_id, acct_id, contact.id,
                                DispatchErrorType.user_blocked,
                                str(exc), owner_id=owner_id,
                            )
                        except UserPrivacyRestricted as exc:
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db, campaign_id, acct_id, contact.id,
                                DispatchErrorType.user_privacy_restricted,
                                str(exc), owner_id=owner_id,
                            )
                        except PeerIdInvalid as exc:
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db, campaign_id, acct_id, contact.id,
                                DispatchErrorType.peer_id_invalid,
                                str(exc), owner_id=owner_id,
                            )
                        except UserAlreadyParticipant as exc:
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db, campaign_id, acct_id, contact.id,
                                DispatchErrorType.other,
                                str(exc), owner_id=owner_id,
                            )
                        except Exception as exc:  # noqa: BLE001
                            sentry_sdk.capture_exception(exc)
                            _log_dispatch_error(
                                db, campaign_id, acct_id, contact.id,
                                DispatchErrorType.other,
                                str(exc), owner_id=owner_id,
                            )

                    # Session is closed — safe to sleep
                    if should_break:
                        break
                    if should_sleep:
                        await asyncio.sleep(random.uniform(40, 120))

        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            with SessionLocal() as db:
                _log_dispatch_error(
                    db, campaign_id, acct_id, None,
                    DispatchErrorType.other, str(exc), owner_id=owner_id,
                )

        if success >= total_contacts:
            break

    # --- Phase 3: final status update ------------------------------------
    with SessionLocal() as db:
        campaign = db.get(Campaign, campaign_id)
        if campaign:
            if success >= total_contacts:
                campaign.status = CampaignStatus.completed
                campaign.progress = 100.0
            db.commit()


@celery_app.task(
    bind=True,
    rate_limit="2/s",
    soft_time_limit=3600,
    time_limit=3900,
)
def campaign_dispatch(self, campaign_id: int) -> None:
    _log_task_started(campaign_id=campaign_id)
    try:
        asyncio.run(_run_campaign_dispatch(campaign_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (campaign_id=%s)", self.request.id, campaign_id)
        with SessionLocal() as db:
            campaign = db.get(Campaign, campaign_id)
            if campaign and campaign.status == CampaignStatus.active:
                campaign.status = CampaignStatus.paused
                db.commit()


@celery_app.task(bind=True, soft_time_limit=300, time_limit=360)
def account_health_check(self, account_id: int) -> None:
    _log_task_started(account_id=account_id)
    try:
        asyncio.run(_run_account_health_check(account_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s)", self.request.id, account_id)


# TODO: заменить Account на TelegramAccount для поддержки per-account api_id
async def _run_account_health_check(account_id: int) -> None:
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if not account:
            logger.info("Account not found", extra={"account_id": account_id})
            return

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        try:
            client = get_client(account, proxy)
        except TelegramClientDisabledError:
            _set_account_cooldown(db, account, 300)
            return
        except RuntimeError as e:
            logger.error(f"Cannot create Telegram client: {e}")
            account.status = AccountStatus.error
            account.last_error = str(e)
            db.commit()
            return

        try:
            async with client:
                await client.get_me()
            account.last_activity_at = datetime.now(timezone.utc)
            if account.status == AccountStatus.cooldown and account.cooldown_until:
                if is_expired(account.cooldown_until):
                    account.status = AccountStatus.active
            db.commit()
            manager.broadcast_sync(
                {
                    "type": "account_update",
                    "user_id": account.owner_id,
                    "account_id": account.id,
                    "status": _serialize_status(account.status),
                    "actions_completed": account.warming_actions_completed,
                    "target_actions": account.target_warming_actions,
                    "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None,
                }
            )
        except FloodWait as exc:
            _set_account_cooldown(db, account, int(exc.value))
        except Exception as exc:  # noqa: BLE001
            logger.info("Account health check failed", extra={"account_id": account_id, "error": str(exc)})


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


# TODO: заменить Account на TelegramAccount для поддержки per-account api_id
async def _run_warming_cycle(account_id: int) -> None:
    # --- Phase 1: load data & build client in a short-lived session -------
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
        try:
            client = get_client(account, proxy)
        except TelegramClientDisabledError:
            _set_account_cooldown(db, account, 300)
            return
        except RuntimeError as e:
            logger.error(f"Cannot create Telegram client: {e}")
            account.status = AccountStatus.error
            account.last_error = str(e)
            db.commit()
            return

        owner_id = account.owner_id
        actions_done = account.warming_actions_completed
        target_actions = account.target_warming_actions or 10
        cooldown_until_iso = account.cooldown_until.isoformat() if account.cooldown_until else None

    # --- Phase 2: warming loop — sessions only for DB writes --------------
    manager.broadcast_sync(
        {
            "type": "account_update",
            "user_id": owner_id,
            "account_id": account_id,
            "status": _serialize_status(AccountStatus.warming),
            "actions_completed": actions_done,
            "target_actions": target_actions,
            "cooldown_until": cooldown_until_iso,
        }
    )

    try:
        async with client:
            while actions_done < target_actions:
                # perform_low_risk_action sleeps 60-300s internally — no DB held
                actions_done += await perform_low_risk_action(client)

                with SessionLocal() as db:
                    account = db.get(Account, account_id)
                    if account:
                        account.warming_actions_completed = actions_done
                        account.last_activity_at = datetime.now(timezone.utc)
                        db.commit()

                manager.broadcast_sync(
                    {
                        "type": "account_update",
                        "user_id": owner_id,
                        "account_id": account_id,
                        "status": _serialize_status(AccountStatus.warming),
                        "actions_completed": actions_done,
                        "target_actions": target_actions,
                        "cooldown_until": None,
                    }
                )

            with SessionLocal() as db:
                account = db.get(Account, account_id)
                if account:
                    account.status = AccountStatus.active
                    db.commit()
    except FloodWait as exc:
        sentry_sdk.capture_exception(exc)
        logger.info(
            "FloodWait during warming",
            extra={"account_id": account_id, "wait_seconds": exc.value},
        )
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account:
                account.status = AccountStatus.cooldown
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=exc.value)
                db.commit()
    except Exception as exc:  # noqa: BLE001
        sentry_sdk.capture_exception(exc)
        logger.error("Warming error", extra={"error": str(exc), "account_id": account_id})
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account:
                account.status = AccountStatus.cooldown
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
                db.commit()

    # --- Phase 3: final broadcast with fresh data -------------------------
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if account:
            manager.broadcast_sync(
                {
                    "type": "account_update",
                    "user_id": owner_id,
                    "account_id": account_id,
                    "status": _serialize_status(account.status),
                    "actions_completed": account.warming_actions_completed,
                    "target_actions": account.target_warming_actions,
                    "cooldown_until": account.cooldown_until.isoformat() if account.cooldown_until else None,
                }
            )


@celery_app.task(
    bind=True,
    soft_time_limit=3600,
    time_limit=3900,
)
def start_warming(self, account_id: int) -> None:
    _log_task_started(account_id=account_id)
    try:
        asyncio.run(_run_warming_cycle(account_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s)", self.request.id, account_id)
        with SessionLocal() as db:
            account = db.get(Account, account_id)
            if account:
                account.status = AccountStatus.cooldown
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
                db.commit()


@celery_app.task(bind=True, soft_time_limit=60, time_limit=90)
def perform_warming_action(self, account_id: int) -> None:
    _log_task_started(account_id=account_id)
    try:
        logger.info("Perform warming action", extra={"account_id": account_id})
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s)", self.request.id, account_id)


@celery_app.task(bind=True, soft_time_limit=60, time_limit=90)
def check_cooldowns(self) -> None:
    _log_task_started()
    try:
        with SessionLocal() as db:
            # TODO: заменить Account на TelegramAccount для поддержки per-account api_id
            accounts = (
                db.query(Account)
                .filter(Account.status == AccountStatus.cooldown)
                .filter(Account.cooldown_until.isnot(None))
                .all()
            )
            for account in accounts:
                if account.cooldown_until and is_expired(account.cooldown_until):
                    account.status = AccountStatus.active
                    manager.broadcast_sync(
                        {
                            "type": "account_update",
                            "user_id": account.owner_id,
                            "account_id": account.id,
                            "status": _serialize_status(account.status),
                            "actions_completed": account.warming_actions_completed,
                            "target_actions": account.target_warming_actions,
                            "cooldown_until": None,
                        }
                    )
            db.commit()
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown", self.request.id)
    except Exception as exc:  # noqa: BLE001
        sentry_sdk.capture_exception(exc)
        logger.exception("check_cooldowns failed: %s", exc)


@celery_app.task(bind=True, soft_time_limit=60, time_limit=90)
def sync_3proxy_config(self) -> None:
    _log_task_started()
    try:
        sync_3proxy()
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown", self.request.id)


@celery_app.task(bind=True, soft_time_limit=300, time_limit=360)
def validate_proxy_task(self, proxy_id: int) -> None:
    _log_task_started()
    try:
        asyncio.run(validate_proxy(proxy_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (proxy_id=%s)", self.request.id, proxy_id)


@celery_app.task(bind=True, soft_time_limit=300, time_limit=360)
def legacy_verify_account(self, account_id: int) -> None:
    """Async-safe verify for legacy Account model.

    Replaces the old blocking verify_account endpoint by offloading
    the Pyrogram get_me() call to a Celery worker.
    """
    _log_task_started(account_id=account_id)
    try:
        asyncio.run(_run_legacy_verify(account_id))
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit, graceful shutdown (account_id=%s)", self.request.id, account_id)


# TODO: заменить Account на TelegramAccount для поддержки per-account api_id
async def _run_legacy_verify(account_id: int) -> None:
    from app.core.metrics import verify_account_duration_seconds, verify_fail_total
    import time as _time

    t0 = _time.monotonic()
    with SessionLocal() as db:
        account = db.get(Account, account_id)
        if not account:
            logger.info("event=legacy_verify_not_found account_id=%d", account_id)
            return

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        try:
            client = get_client(account, proxy)
        except TelegramClientDisabledError:
            logger.warning("event=legacy_verify_failed reason=client_disabled account_id=%d", account_id)
            verify_fail_total.labels(reason="client_disabled").inc()
            return
        except RuntimeError as e:
            logger.error(f"Cannot create Telegram client: {e}")
            verify_fail_total.labels(reason="runtime_error").inc()
            account.status = AccountStatus.error
            account.last_error = str(e)
            db.commit()
            return

        try:
            async with client:
                me = await client.get_me()
        except FloodWait as exc:
            elapsed = _time.monotonic() - t0
            verify_account_duration_seconds.observe(elapsed)
            verify_fail_total.labels(reason="floodwait").inc()
            _set_account_cooldown(db, account, int(exc.value))
            logger.warning(
                "event=legacy_verify_failed reason=floodwait wait_s=%d account_id=%d elapsed_s=%.3f",
                exc.value, account_id, elapsed,
            )
            return
        except Exception as exc:
            elapsed = _time.monotonic() - t0
            verify_account_duration_seconds.observe(elapsed)
            verify_fail_total.labels(reason="unknown").inc()
            logger.exception(
                "event=legacy_verify_failed reason=exception account_id=%d error=%s elapsed_s=%.3f",
                account_id, str(exc)[:200], elapsed,
            )
            return

        elapsed = _time.monotonic() - t0
        verify_account_duration_seconds.observe(elapsed)
        logger.info(
            "event=legacy_verify_ok account_id=%d result=ok elapsed_s=%.3f",
            account_id, elapsed,
        )

        account.telegram_id = me.id
        account.username = me.username
        account.first_name = me.first_name
        account.status = AccountStatus.verified
        account.last_activity_at = datetime.now(timezone.utc)
        db.commit()

        manager.broadcast_sync({
            "type": "account_update",
            "user_id": account.owner_id,
            "account_id": account.id,
            "status": _serialize_status(account.status),
        })
