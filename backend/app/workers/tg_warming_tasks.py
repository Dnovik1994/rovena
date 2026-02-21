"""Celery tasks for TelegramAccount warming cycle.

Day-based warming: each invocation runs one day's plan, then increments
warming_day.  Day 0 is rest (отлёжка), days 1-14 gradually increase
activity, day 15+ checks for completion.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone

import sentry_sdk
from celery.exceptions import SoftTimeLimitExceeded
from pyrogram.errors import AuthKeyUnregistered, FloodWait, UserDeactivatedBan

from app.clients.telegram_client import TelegramClientDisabledError, create_tg_account_client
from app.workers.tg_timeout_helpers import collect_async_gen, safe_call
from app.core.database import SessionLocal
from app.core.tz import is_expired
from app.core.settings import get_settings
from app.models.proxy import Proxy
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.warming_channel import WarmingChannel
from app.services.notification_service import NotificationService, send_notification_sync
from app.services.websocket_manager import manager
from app.workers import celery_app
from app.workers.tg_warming_helpers import is_quiet_hours
from app.workers.tg_warming_actions import (
    _action_add_contacts,
    _action_go_online,
    _action_set_bio,
    _action_set_name,
    _action_set_photo,
    _action_set_username,
    _action_trusted_conversation,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# WebSocket broadcast helpers
# ---------------------------------------------------------------------------

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


def _broadcast_account_update(account) -> None:
    """Broadcast a simple account status change."""
    _broadcast_warming_update(
        account.owner_user_id,
        account.id,
        account.status,
        account.warming_actions_completed,
        account.target_warming_actions or 10,
        account.cooldown_until.isoformat() if account.cooldown_until else None,
    )


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------

async def _send_notification(event_type: str, message: str) -> None:
    """Send notification from async context."""
    settings = get_settings()
    if not settings.telegram_bot_token:
        return
    try:
        service = NotificationService(settings.telegram_bot_token)
        await service.send(event_type, message)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to send notification: %s", event_type)


def format_flood_message(account, wait_seconds: int) -> str:
    return (
        f"⚠️ FloodWait\n"
        f"📱 {account.phone_e164} (ID: {account.id})\n"
        f"⏱ Ждать: {wait_seconds}с\n"
        f"📊 День: {account.warming_day}/15\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


def format_banned_message(account, error: str) -> str:
    return (
        f"🚫 Аккаунт забанен\n"
        f"📱 {account.phone_e164} (ID: {account.id})\n"
        f"📝 Причина: {error}\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


def format_error_message(account, error: str) -> str:
    return (
        f"❌ Ошибка прогрева\n"
        f"📱 {account.phone_e164} (ID: {account.id})\n"
        f"📝 {error[:200]}\n"
        f"📊 День: {account.warming_day}/15\n"
        f"🕐 {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}"
    )


# ---------------------------------------------------------------------------
# Channel/group action wrappers (new signature: client, account, db, **params)
# ---------------------------------------------------------------------------

def _get_joined_channels(account) -> list[str]:
    """Extract joined channel usernames from warming_joined_channels JSON."""
    data = account.warming_joined_channels
    if isinstance(data, dict):
        return list(data.get("channels", []))
    if isinstance(data, list):
        return list(data)
    return []


def _save_joined_channels(account, channels: list[str]) -> None:
    """Persist joined channel list back to warming_joined_channels JSON."""
    data = account.warming_joined_channels
    if not isinstance(data, dict):
        data = {"channels": [], "done_once": []}
    data["channels"] = channels
    account.warming_joined_channels = data


async def _action_join_channels(client, account, db, **params) -> bool:
    """Join ``count`` public channels from the WarmingChannel pool."""
    count = params.get("count", 1)
    if count <= 0:
        return True

    channels = (
        db.query(WarmingChannel)
        .filter_by(is_active=True, channel_type="channel")
        .all()
    )
    already = set(_get_joined_channels(account))
    not_joined = [c for c in channels if c.username not in already]
    if not not_joined:
        logger.info("No unjoin channels left for account %s", account.id)
        return False

    to_join = random.sample(not_joined, min(count, len(not_joined)))
    joined_any = False
    for ch in to_join:
        result = await safe_call(client.join_chat(ch.username), timeout=30)
        if result is not None:
            already.add(ch.username)
            joined_any = True
        await asyncio.sleep(random.uniform(5, 15))

    _save_joined_channels(account, list(already))
    db.commit()
    return joined_any


async def _action_join_groups(client, account, db, **params) -> bool:
    """Join ``count`` groups from the WarmingChannel pool (channel_type='group')."""
    count = params.get("count", 1)
    if count <= 0:
        return True

    groups = (
        db.query(WarmingChannel)
        .filter_by(is_active=True, channel_type="group")
        .all()
    )
    already = set(_get_joined_channels(account))
    not_joined = [g for g in groups if g.username not in already]
    if not not_joined:
        logger.info("No unjoined groups left for account %s", account.id)
        return False

    to_join = random.sample(not_joined, min(count, len(not_joined)))
    joined_any = False
    for g in to_join:
        result = await safe_call(client.join_chat(g.username), timeout=30)
        if result is not None:
            already.add(g.username)
            joined_any = True
        await asyncio.sleep(random.uniform(5, 15))

    _save_joined_channels(account, list(already))
    db.commit()
    return joined_any


async def _action_read_channels(client, account, db, **params) -> bool:
    """Read recent messages from ``count`` joined channels."""
    count = params.get("count", 1)
    already = _get_joined_channels(account)
    if not already:
        return False

    targets = random.sample(already, min(count, len(already)))
    read_any = False
    for ch in targets:
        messages = await collect_async_gen(
            client.get_chat_history(ch, limit=random.randint(3, 10)),
            timeout=60,
        )
        if messages:
            read_any = True
        await asyncio.sleep(random.uniform(3, 10))

    return read_any


async def _action_react(client, account, db, **params) -> bool:
    """React to messages in ``count`` joined channels."""
    count = params.get("count", 1)
    already = _get_joined_channels(account)
    if not already:
        return False

    targets = random.sample(already, min(count, len(already)))
    reacted_any = False
    emojis = ["👍", "❤️", "🔥", "👏", "😂", "🎉", "💯", "👀"]

    for ch in targets:
        messages = await collect_async_gen(
            client.get_chat_history(ch, limit=5), timeout=60,
        )
        if messages:
            msg = random.choice(messages)
            emoji = random.choice(emojis)
            await safe_call(
                client.send_reaction(ch, msg.id, emoji=emoji), timeout=15,
            )
            reacted_any = True
        await asyncio.sleep(random.uniform(5, 15))

    return reacted_any


async def _action_send_saved(client, account, db, **params) -> bool:
    """Send a short message to Saved Messages."""
    phrases = [
        "📝 заметка", "⭐ запомнить", "🔗 ссылка",
        "📅 дела", "💡 идея", "✅ готово",
        str(random.randint(1000, 9999)),
    ]
    result = await safe_call(
        client.send_message("me", random.choice(phrases)), timeout=15,
    )
    return result is not None


# ---------------------------------------------------------------------------
# ACTION_MAP — maps plan step names to async functions
# ---------------------------------------------------------------------------

ACTION_MAP = {
    "go_online": _action_go_online,
    "set_photo": _action_set_photo,
    "set_bio": _action_set_bio,
    "set_username": _action_set_username,
    "set_name": _action_set_name,
    "add_contacts": _action_add_contacts,
    "trusted_conversation": _action_trusted_conversation,
    "join_channels": _action_join_channels,
    "join_groups": _action_join_groups,
    "read_channels": _action_read_channels,
    "react": _action_react,
    "send_saved_message": _action_send_saved,
}


# ---------------------------------------------------------------------------
# _safe_action — wraps action execution with error handling
# ---------------------------------------------------------------------------

async def _safe_action(action_fn, client, account, db, **params) -> bool:
    """Execute an action with per-action error handling.

    Returns True if the action succeeded, False otherwise.
    Re-raises FloodWait, UserDeactivatedBan, AuthKeyUnregistered so the
    caller can handle them at the cycle level.
    """
    try:
        result = await action_fn(client, account, db, **params)
        return bool(result) if result is not None else True
    except (FloodWait, UserDeactivatedBan, AuthKeyUnregistered):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Warming action %s failed (account_id=%s): %s",
            getattr(action_fn, "__name__", "?"),
            account.id,
            exc,
        )
        return False


# ---------------------------------------------------------------------------
# Daily plan
# ---------------------------------------------------------------------------

def _get_daily_plan(warming_day: int, account, db) -> list[dict]:
    """Return the list of actions for a specific warming day."""

    if warming_day == 0:
        return []  # rest period

    if warming_day == 1:
        return [
            {"action": "go_online"},
            {"action": "set_photo"},
        ]

    if warming_day == 2:
        return [
            {"action": "go_online"},
            {"action": "add_contacts"},
        ]

    if warming_day == 3:
        return [
            {"action": "go_online"},
            {"action": "trusted_conversation"},
            {"action": "send_saved_message"},
        ]

    if warming_day == 4:
        return [
            {"action": "go_online"},
            {"action": "join_channels", "params": {"count": random.randint(1, 2)}},
            {"action": "read_channels", "params": {"count": 2}},
        ]

    if warming_day == 5:
        return [
            {"action": "go_online"},
            {"action": "set_bio"},
            {"action": "join_channels", "params": {"count": 1}},
            {"action": "react", "params": {"count": 1}},
        ]

    if warming_day in (6, 7):
        return [
            {"action": "go_online"},
            {"action": "join_groups", "params": {"count": 1}},
            {"action": "react", "params": {"count": random.randint(1, 2)}},
            {"action": "read_channels", "params": {"count": 2}},
        ]

    if warming_day in (8, 9):
        plan = [
            {"action": "go_online"},
            {"action": "join_channels", "params": {"count": random.randint(1, 2)}},
            {"action": "react", "params": {"count": random.randint(2, 3)}},
        ]
        if warming_day == 8:
            plan.insert(1, {"action": "set_username"})
        return plan

    if warming_day in (10, 11):
        return [
            {"action": "go_online"},
            {"action": "read_channels", "params": {"count": 3}},
            {"action": "react", "params": {"count": random.randint(2, 3)}},
            {"action": "send_saved_message"},
        ]

    if warming_day in (12, 13):
        plan = [
            {"action": "go_online"},
            {"action": "read_channels", "params": {"count": 3}},
            {"action": "react", "params": {"count": random.randint(2, 4)}},
            {"action": "join_channels", "params": {"count": 1}},
            {"action": "send_saved_message"},
        ]
        if warming_day == 12:
            plan.insert(1, {"action": "set_name"})
        return plan

    # warming_day >= 14
    return [
        {"action": "go_online"},
        {"action": "read_channels", "params": {"count": random.randint(3, 5)}},
        {"action": "react", "params": {"count": random.randint(3, 5)}},
        {"action": "join_channels", "params": {"count": random.randint(0, 1)}},
        {"action": "send_saved_message"},
    ]


# ---------------------------------------------------------------------------
# Main warming cycle (day-based)
# ---------------------------------------------------------------------------

async def _run_tg_warming_cycle(account_id: int) -> None:
    """Day-based warming cycle for TelegramAccount.

    Each invocation executes one day's plan, then increments warming_day.
    Day 0 is rest (отлёжка).  Days 1-14 gradually increase activity.
    When warming_day reaches 15 without recent FloodWait → status = active.
    """
    db = SessionLocal()
    try:
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

        # --- Rest period check (day 0) ---
        if account.warming_day == 0:
            settings = get_settings()
            rest_hours = random.uniform(
                settings.warming_rest_hours_min,
                settings.warming_rest_hours_max,
            )
            if account.warming_started_at + timedelta(hours=rest_hours) > datetime.now(timezone.utc):
                logger.info(
                    "Account %s still in rest period (day 0)", account_id,
                )
                return  # still resting
            account.warming_day = 1
            db.commit()

        # --- Build daily plan ---
        plan = _get_daily_plan(account.warming_day, account, db)
        if not plan:
            return

        # --- Create Telegram client ---
        proxy = db.get(Proxy, account.proxy_id) if account.proxy_id else None
        try:
            client = create_tg_account_client(
                account, proxy, phone=account.phone_e164,
                in_memory=False, workdir="/data/pyrogram_sessions",
            )
        except TelegramClientDisabledError:
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=300)
            account.last_error = "Telegram client disabled"
            db.commit()
            return
        except RuntimeError as e:
            logger.error(
                "Cannot create Telegram client: %s", e,
                extra={"account_id": account_id},
            )
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
            account.last_error = str(e)[:500]
            db.commit()
            return

        try:
            async with client:
                # --- Execute daily plan ---
                for step in plan:
                    action_fn = ACTION_MAP.get(step["action"])
                    if not action_fn:
                        logger.warning(
                            "Unknown action %r in plan for account %s",
                            step["action"], account_id,
                        )
                        continue

                    params = step.get("params", {})
                    success = await _safe_action(
                        action_fn, client, account, db, **params,
                    )

                    # Persist progress
                    if success:
                        account.warming_actions_completed += 1
                    account.last_activity_at = datetime.now(timezone.utc)
                    db.commit()

                    # Pause between actions (go_online already has its own sleep)
                    if step["action"] != "go_online":
                        await asyncio.sleep(random.uniform(15, 45))

                # --- Day completed successfully → increment ---
                account.warming_day += 1

                # Day 15+ without recent FloodWait → active
                if account.warming_day >= 15:
                    last_flood = account.flood_wait_at
                    if not last_flood or (datetime.now(timezone.utc) - last_flood).days >= 14:
                        account.status = TelegramAccountStatus.active
                        account.last_error = None
                        await _send_notification(
                            "warming_completed",
                            f"✅ Прогрев завершён\n"
                            f"📱 {account.phone_e164} (ID: {account.id})\n"
                            f"📊 Дней: {account.warming_day}",
                        )

                db.commit()
                _broadcast_account_update(account)

        except FloodWait as exc:
            sentry_sdk.capture_exception(exc)
            wait_seconds = int(exc.value)
            logger.info(
                "FloodWait during TG warming",
                extra={"account_id": account_id, "wait_seconds": wait_seconds},
            )
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=wait_seconds)
            account.flood_wait_at = datetime.now(timezone.utc)
            account.warming_day = max(1, account.warming_day - 3)
            account.last_error = f"FloodWait: {wait_seconds}s"
            db.commit()
            await _send_notification(
                "flood_wait", format_flood_message(account, wait_seconds),
            )

        except (UserDeactivatedBan, AuthKeyUnregistered) as exc:
            sentry_sdk.capture_exception(exc)
            logger.warning(
                "Account banned/deactivated during warming",
                extra={"account_id": account_id, "error": str(exc)},
            )
            account.status = TelegramAccountStatus.banned
            account.last_error = str(exc)[:500]
            db.commit()
            await _send_notification(
                "account_banned",
                format_banned_message(account, str(exc)),
            )

        except Exception as exc:  # noqa: BLE001
            sentry_sdk.capture_exception(exc)
            logger.error(
                "TG warming error",
                extra={"error": str(exc), "account_id": account_id},
            )
            # Generic error → cooldown 1 hour (NOT error!)
            account.status = TelegramAccountStatus.cooldown
            account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
            account.last_error = str(exc)[:500]
            db.commit()
            await _send_notification(
                "warming_failed",
                format_error_message(account, str(exc)),
            )

        # Final broadcast with fresh data
        _broadcast_account_update(account)

    finally:
        db.close()


# ---------------------------------------------------------------------------
# Celery entry-point
# ---------------------------------------------------------------------------

@celery_app.task(
    bind=True,
    soft_time_limit=5400,
    time_limit=5700,
)
def start_tg_warming(self, account_id: int) -> None:
    """Celery entry-point for TelegramAccount warming."""
    if is_quiet_hours():
        logger.info("Quiet hours active, skipping warming")
        return

    task_id = self.request.id
    logger.info("event=start_tg_warming_started account_id=%s task_id=%s", account_id, task_id)

    # Acquire warming lease to prevent duplicate tasks
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        if not account:
            logger.info("TelegramAccount not found for lease", extra={"account_id": account_id})
            return
        if not account.acquire_warming_lease(task_id, db):
            logger.info(
                "event=warming_lease_not_acquired account_id=%s task_id=%s",
                account_id, task_id,
            )
            return

    try:
        asyncio.run(_run_tg_warming_cycle(account_id))
    except SoftTimeLimitExceeded:
        logger.warning(
            "Task %s hit soft time limit (account_id=%s)", task_id, account_id,
        )
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if account:
                account.status = TelegramAccountStatus.cooldown
                account.cooldown_until = datetime.now(timezone.utc) + timedelta(hours=1)
                account.last_error = "Warming task timed out"
                db.commit()
    finally:
        # Always release the warming lease
        with SessionLocal() as db:
            account = db.get(TelegramAccount, account_id)
            if account:
                account.release_warming_lease(db)

    logger.info("event=start_tg_warming_finished account_id=%s", account_id)


# ---------------------------------------------------------------------------
# Periodic tasks (celery beat)
# ---------------------------------------------------------------------------

def _get_max_concurrent() -> int:
    return get_settings().warming_max_concurrent


@celery_app.task(bind=True, soft_time_limit=60, time_limit=90)
def check_tg_cooldowns(self) -> None:
    """Transition TelegramAccounts out of cooldown when cooldown_until expires.

    Logic:
    - warming_day >= 15 AND (flood_wait_at IS NULL OR flood_wait_at > 14 days ago)
      → status = active
    - Otherwise → back to warming
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
            now = datetime.now(timezone.utc)
            for account in accounts:
                if not is_expired(account.cooldown_until):
                    continue

                # Determine new status based on warming progress
                if account.warming_day >= 15:
                    last_flood = account.flood_wait_at
                    if not last_flood or (now - last_flood).days >= 14:
                        new_status = TelegramAccountStatus.active
                    else:
                        new_status = TelegramAccountStatus.warming
                else:
                    new_status = TelegramAccountStatus.warming

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
                    account.target_warming_actions or 10,
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
    - skip accounts with an active warming lease (task still running)
    - limit to warming_max_concurrent dispatches per run
    """
    if is_quiet_hours():
        logger.info("Quiet hours active, skipping warming dispatch")
        return

    logger.info("event=resume_tg_warming_started task_id=%s", self.request.id)
    try:
        now = datetime.now(timezone.utc)
        lease_ttl = timedelta(seconds=5400)  # 90 minutes

        with SessionLocal() as db:
            accounts = (
                db.query(TelegramAccount)
                .filter(TelegramAccount.status == TelegramAccountStatus.warming)
                .limit(_get_max_concurrent())
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

                # Skip if warming lease is active (task still running)
                if (
                    account.warming_task_id is not None
                    and account.warming_task_started_at is not None
                    and account.warming_task_started_at > now - lease_ttl
                ):
                    logger.debug(
                        "event=resume_tg_warming_skip account_id=%s reason=lease_active task_id=%s",
                        account.id,
                        account.warming_task_id,
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
