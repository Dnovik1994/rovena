"""Celery tasks for TelegramAccount warming cycle.

Replaces the legacy start_warming (tasks.py) which works with the old
Account model.  This module uses TelegramAccount + create_tg_account_client
so per-account api_id / encrypted sessions are handled correctly.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import sentry_sdk
from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import FloodWait

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.core.database import SessionLocal
from app.core.settings import get_settings
from app.core.tz import is_expired
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.services.websocket_manager import manager
from app.workers import celery_app

logger = logging.getLogger(__name__)
settings = get_settings()

if settings.redis_url:
    manager.configure_redis(settings.redis_url)


def _serialize_status(status: TelegramAccountStatus) -> str:
    return status.value if hasattr(status, "value") else str(status)


def _broadcast_warming_update(
    owner_user_id: int,
    account_id: int,
    status: TelegramAccountStatus,
    actions_completed: int,
    target_actions: int,
    cooldown_until: str | None,
) -> None:
    manager.broadcast_sync(
        {
            "type": "account_update",
            "user_id": owner_user_id,
            "account_id": account_id,
            "status": _serialize_status(status),
            "actions_completed": actions_completed,
            "target_actions": target_actions,
            "cooldown_until": cooldown_until,
        }
    )


async def _perform_low_risk_action(client) -> int:
    """Execute a few random low-risk Telegram actions.

    Returns the number of actions performed.
    """
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


async def _run_tg_warming_cycle(account_id: int) -> None:
    """Three-phase warming cycle for TelegramAccount."""

    # --- Phase 1: load data & build client -----------------------------------
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        if not account:
            logger.info("TelegramAccount not found", extra={"account_id": account_id})
            return

        if account.status != TelegramAccountStatus.warming:
            logger.info(
                "TelegramAccount not in warming status",
                extra={"account_id": account_id, "status": account.status},
            )
            return

        if not account.warming_started_at:
            account.warming_started_at = datetime.now(timezone.utc)
            db.commit()

        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        try:
            client = create_tg_account_client(account, proxy, phone=account.phone_e164)
        except TelegramClientDisabledError:
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=300)
            account.last_error = "Telegram client disabled"
            db.commit()
            return
        except RuntimeError as e:
            logger.error("Cannot create Telegram client: %s", e, extra={"account_id": account_id})
            account.status = TelegramAccountStatus.error
            account.last_error = str(e)
            db.commit()
            return

        owner_user_id = account.owner_user_id
        actions_done = account.warming_actions_completed
        target_actions = account.target_warming_actions or 10
        cooldown_until_iso = account.cooldown_until.isoformat() if account.cooldown_until else None

    # --- Phase 2: warming loop -----------------------------------------------
    _broadcast_warming_update(
        owner_user_id, account_id,
        TelegramAccountStatus.warming,
        actions_done, target_actions, cooldown_until_iso,
    )

    try:
        async with client:
            while actions_done < target_actions:
                actions_done += await _perform_low_risk_action(client)

                with SessionLocal() as db:
                    account = db.get(TelegramAccount, account_id)
                    if account:
                        account.warming_actions_completed = actions_done
                        account.last_activity_at = datetime.now(timezone.utc)
                        db.commit()

                _broadcast_warming_update(
                    owner_user_id, account_id,
                    TelegramAccountStatus.warming,
                    actions_done, target_actions, None,
                )

            # Warming complete — mark active
            with SessionLocal() as db:
                account = db.get(TelegramAccount, account_id)
                if account:
                    account.status = TelegramAccountStatus.active
                    account.last_error = None
                    db.commit()

    except FloodWait as exc:
        sentry_sdk.capture_exception(exc)
        wait_seconds = int(exc.value)
        logger.info(
            "FloodWait during TG warming",
            extra={"account_id": account_id, "wait_seconds": wait_seconds},
        )
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if account:
                account.status = TelegramAccountStatus.cooldown
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
                account.last_error = f"FloodWait: {wait_seconds}s"
                db.commit()

    except Exception as exc:  # noqa: BLE001
        sentry_sdk.capture_exception(exc)
        logger.error("TG warming error", extra={"error": str(exc), "account_id": account_id})
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if account:
                account.status = TelegramAccountStatus.error
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
                account.last_error = str(exc)[:500]
                db.commit()

    # --- Phase 3: final broadcast with fresh data ----------------------------
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        if account:
            _broadcast_warming_update(
                owner_user_id, account_id,
                account.status,
                account.warming_actions_completed,
                account.target_warming_actions,
                account.cooldown_until.isoformat() if account.cooldown_until else None,
            )


@celery_app.task(
    bind=True,
    soft_time_limit=3600,
    time_limit=3900,
)
def start_tg_warming(self, account_id: int) -> None:
    """Celery entry-point for TelegramAccount warming."""
    logger.info("event=start_tg_warming_started account_id=%s task_id=%s", account_id, self.request.id)
    try:
        asyncio.run(_run_tg_warming_cycle(account_id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "Task %s hit soft time limit (account_id=%s)", self.request.id, account_id,
        )
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if account:
                account.status = TelegramAccountStatus.cooldown
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
                account.last_error = "Warming task timed out"
                db.commit()
    logger.info("event=start_tg_warming_finished account_id=%s", account_id)


# ---------------------------------------------------------------------------
# Periodic tasks (celery beat)
# ---------------------------------------------------------------------------

MAX_CONCURRENT_WARMING_TASKS = 5


@celery_app.task(bind=True, soft_time_limit=60, time_limit=90)
def check_tg_cooldowns(self) -> None:
    """Transition TelegramAccounts out of cooldown when cooldown_until expires.

    - warming_actions_completed < target → back to ``warming``
    - otherwise → ``active``
    """
    logger.info("event=check_tg_cooldowns_started task_id=%s", self.request.id)
    try:
        with SessionLocal() as db:
            accounts = (
                db.query(TelegramAccount)
                .filter(TelegramAccount.status == TelegramAccountStatus.cooldown)
                .filter(TelegramAccount.cooldown_until.isnot(None))
                .all()
            )
            for account in accounts:
                if not is_expired(account.cooldown_until):
                    continue

                target = account.target_warming_actions or 10
                if account.warming_actions_completed < target:
                    new_status = TelegramAccountStatus.warming
                else:
                    new_status = TelegramAccountStatus.active

                old_status = account.status
                account.status = new_status
                account.cooldown_until = None
                account.last_error = None

                logger.info(
                    "event=tg_cooldown_expired account_id=%s old_status=%s new_status=%s",
                    account.id,
                    old_status,
                    new_status,
                )
                _broadcast_warming_update(
                    account.owner_user_id,
                    account.id,
                    new_status,
                    account.warming_actions_completed,
                    target,
                    None,
                )
            db.commit()
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit", self.request.id)
    except Exception as exc:  # noqa: BLE001
        sentry_sdk.capture_exception(exc)
        logger.exception("check_tg_cooldowns failed: %s", exc)


@celery_app.task(bind=True, soft_time_limit=60, time_limit=90)
def resume_tg_warming(self) -> None:
    """Dispatch start_tg_warming for accounts stuck in ``warming`` status.

    Guards:
    - skip accounts whose cooldown_until is still in the future (task recently
      set cooldown but status was reverted before commit — defensive)
    - limit to MAX_CONCURRENT_WARMING_TASKS dispatches per run
    """
    logger.info("event=resume_tg_warming_started task_id=%s", self.request.id)
    try:
        with SessionLocal() as db:
            accounts = (
                db.query(TelegramAccount)
                .filter(TelegramAccount.status == TelegramAccountStatus.warming)
                .limit(MAX_CONCURRENT_WARMING_TASKS)
                .all()
            )

            dispatched = 0
            for account in accounts:
                # Skip if cooldown_until is set and still in the future —
                # means a warming task recently put it in cooldown but the
                # status hasn't been updated yet (race).
                if account.cooldown_until and not is_expired(account.cooldown_until):
                    logger.debug(
                        "event=resume_tg_warming_skip account_id=%s reason=cooldown_active",
                        account.id,
                    )
                    continue

                start_tg_warming.delay(account.id)
                dispatched += 1
                logger.info(
                    "event=resume_tg_warming_dispatched account_id=%s",
                    account.id,
                )

            logger.info(
                "event=resume_tg_warming_finished dispatched=%s total_warming=%s",
                dispatched,
                len(accounts),
            )
    except SoftTimeLimitExceeded:
        logger.warning("Task %s hit soft time limit", self.request.id)
    except Exception as exc:  # noqa: BLE001
        sentry_sdk.capture_exception(exc)
        logger.exception("resume_tg_warming failed: %s", exc)
