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
from app.models.warming_channel import WarmingChannel
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


# ---------------------------------------------------------------------------
# Legacy low-risk action (kept for backwards compatibility)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Extended warming actions
# ---------------------------------------------------------------------------

async def _action_read_channel(client, channel_username: str) -> int:
    """Read recent messages from a channel."""
    messages = await client.get_history(channel_username, limit=random.randint(3, 10))
    return len(messages) if messages else 0


async def _action_react_to_message(client, channel_username: str) -> bool:
    """React to a random recent message in a channel."""
    messages = await client.get_history(channel_username, limit=5)
    if messages:
        msg = random.choice(messages)
        emoji = random.choice(["👍", "❤️", "🔥", "👏", "😂", "🎉", "💯", "👀"])
        await client.send_reaction(channel_username, msg.id, emoji)
        return True
    return False


async def _action_join_channel(client, channel_username: str) -> bool:
    """Join a public channel or group."""
    await client.join_chat(channel_username)
    return True


async def _action_view_profile(client) -> bool:
    """View own profile (get_me)."""
    await client.get_me()
    return True


async def _action_get_dialogs(client) -> bool:
    """Fetch dialog list."""
    await client.get_dialogs(limit=random.randint(3, 10))
    return True


async def _action_send_saved_message(client) -> bool:
    """Send a short message to Saved Messages."""
    phrases = [
        "📝 заметка", "⭐ запомнить", "🔗 ссылка",
        "📅 дела", "💡 идея", "✅ готово",
        str(random.randint(1000, 9999)),
    ]
    await client.send_message("me", random.choice(phrases))
    return True


async def _action_update_profile(client) -> bool:
    """Update bio (one-time action)."""
    bios = [
        "", "🇺🇦", "👋", "📱", "🌍",
        "Life is good", "Hello world", "🎵🎶",
    ]
    await client.update_profile(bio=random.choice(bios))
    return True


async def _action_set_profile_photo(client) -> bool:
    """Set profile photo (stub — needs actual photos)."""
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_action(coro, action_name: str, account_id: int) -> bool:
    """Execute an action with per-action error handling.

    Returns True if the action succeeded, False otherwise.
    Raises FloodWait so the caller can enter cooldown.
    """
    try:
        result = await coro
        return bool(result) if result is not None else True
    except FloodWait:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Warming action failed: %s (account_id=%s): %s",
            action_name, account_id, exc,
        )
        return False


async def _sleep_between_actions() -> None:
    """Sleep between individual actions within a phase."""
    await asyncio.sleep(random.uniform(45, 180))


async def _sleep_between_phases() -> None:
    """Sleep between warming phases (5-15 minutes)."""
    await asyncio.sleep(random.uniform(300, 900))


def _persist_progress(
    account_id: int,
    actions_done: int,
    joined_channels: list[str] | None = None,
) -> None:
    """Persist warming progress to DB."""
    with SessionLocal() as db:
        account = db.get(TelegramAccount, account_id)
        if account:
            account.warming_actions_completed = actions_done
            account.last_activity_at = datetime.now(timezone.utc)
            if joined_channels is not None:
                account.warming_joined_channels = joined_channels
            db.commit()


# ---------------------------------------------------------------------------
# Phased warming cycle
# ---------------------------------------------------------------------------

async def _run_tg_warming_cycle(account_id: int) -> None:
    """Phased warming cycle for TelegramAccount.

    Phase 1: Basic activity (get_me, get_dialogs, read 1-2 channels)
    Phase 2: Join 2-3 channels, read their history
    Phase 3: React to messages in joined channels
    Phase 4: Profile update + saved messages
    """

    # --- Load data & build client --------------------------------------------
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
        already_joined: list[str] = list(account.warming_joined_channels or [])

        # Load warming channels from DB
        channel_channels = (
            db.query(WarmingChannel)
            .filter_by(is_active=True, channel_type="channel")
            .all()
        )
        channel_groups = (
            db.query(WarmingChannel)
            .filter_by(is_active=True, channel_type="group")
            .all()
        )

    # Keep local copies of usernames (DB session is closed)
    available_channels = [c.username for c in channel_channels]
    available_groups = [c.username for c in channel_groups]
    all_channels = available_channels + available_groups

    # --- Broadcast initial status --------------------------------------------
    _broadcast_warming_update(
        owner_user_id, account_id,
        TelegramAccountStatus.warming,
        actions_done, target_actions, cooldown_until_iso,
    )

    # Track channels joined during this cycle for reactions later
    joined_this_cycle: list[str] = []

    try:
        async with client:

            # ── Phase 1: Basic activity ──────────────────────────────────
            logger.info("event=warming_phase1 account_id=%s", account_id)

            # Action 1: view profile
            if await _safe_action(
                _action_view_profile(client), "view_profile", account_id
            ):
                actions_done += 1
            _persist_progress(account_id, actions_done)
            await _sleep_between_actions()

            # Action 2: get dialogs
            if await _safe_action(
                _action_get_dialogs(client), "get_dialogs", account_id
            ):
                actions_done += 1
            _persist_progress(account_id, actions_done)
            await _sleep_between_actions()

            # Action 3: read 1-2 channels
            read_channels = random.sample(
                available_channels, min(random.randint(1, 2), len(available_channels))
            ) if available_channels else []
            for ch in read_channels:
                if await _safe_action(
                    _action_read_channel(client, ch), f"read_channel:{ch}", account_id
                ):
                    actions_done += 1
                _persist_progress(account_id, actions_done)
                await _sleep_between_actions()

            _broadcast_warming_update(
                owner_user_id, account_id,
                TelegramAccountStatus.warming,
                actions_done, target_actions, None,
            )

            # ── Phase pause ──────────────────────────────────────────────
            await _sleep_between_phases()

            # ── Phase 2: Join channels ───────────────────────────────────
            logger.info("event=warming_phase2 account_id=%s", account_id)

            # Pick 2-3 channels the account hasn't joined yet
            not_joined = [c for c in all_channels if c not in already_joined]
            to_join = random.sample(
                not_joined, min(random.randint(2, 3), len(not_joined))
            ) if not_joined else []

            for ch in to_join:
                if await _safe_action(
                    _action_join_channel(client, ch), f"join_channel:{ch}", account_id
                ):
                    actions_done += 1
                    already_joined.append(ch)
                    joined_this_cycle.append(ch)
                _persist_progress(account_id, actions_done, already_joined)
                await _sleep_between_actions()

            # Read history of joined channels
            for ch in joined_this_cycle:
                if await _safe_action(
                    _action_read_channel(client, ch), f"read_joined:{ch}", account_id
                ):
                    actions_done += 1
                _persist_progress(account_id, actions_done, already_joined)
                await _sleep_between_actions()

            _broadcast_warming_update(
                owner_user_id, account_id,
                TelegramAccountStatus.warming,
                actions_done, target_actions, None,
            )

            # ── Phase pause ──────────────────────────────────────────────
            await _sleep_between_phases()

            # ── Phase 3: Reactions ───────────────────────────────────────
            logger.info("event=warming_phase3 account_id=%s", account_id)

            # React to 2-3 messages in channels we joined (or any already-joined)
            react_targets = joined_this_cycle or [
                c for c in already_joined if c in available_channels
            ]
            react_channels = random.sample(
                react_targets, min(random.randint(2, 3), len(react_targets))
            ) if react_targets else []

            for ch in react_channels:
                if await _safe_action(
                    _action_react_to_message(client, ch),
                    f"react:{ch}", account_id,
                ):
                    actions_done += 1
                _persist_progress(account_id, actions_done, already_joined)
                await _sleep_between_actions()

            _broadcast_warming_update(
                owner_user_id, account_id,
                TelegramAccountStatus.warming,
                actions_done, target_actions, None,
            )

            # ── Phase pause ──────────────────────────────────────────────
            await _sleep_between_phases()

            # ── Phase 4: Profile & saved messages ────────────────────────
            logger.info("event=warming_phase4 account_id=%s", account_id)

            # Update bio (one-time)
            if await _safe_action(
                _action_update_profile(client), "update_profile", account_id
            ):
                actions_done += 1
            _persist_progress(account_id, actions_done, already_joined)
            await _sleep_between_actions()

            # Send 1-2 saved messages
            for _ in range(random.randint(1, 2)):
                if await _safe_action(
                    _action_send_saved_message(client),
                    "send_saved_message", account_id,
                ):
                    actions_done += 1
                _persist_progress(account_id, actions_done, already_joined)
                await _sleep_between_actions()

            # ── Warming complete — mark active ───────────────────────────
            with SessionLocal() as db:
                account = db.get(TelegramAccount, account_id)
                if account:
                    account.status = TelegramAccountStatus.active
                    account.warming_actions_completed = actions_done
                    account.warming_joined_channels = already_joined
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
                account.warming_joined_channels = already_joined
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
                account.warming_joined_channels = already_joined
                db.commit()

    # --- Final broadcast with fresh data -------------------------------------
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
