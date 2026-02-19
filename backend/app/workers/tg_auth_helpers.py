"""Shared helper functions for Telegram authentication tasks.

Pure utilities with no Celery dependency — safe to import from any module.
"""

import inspect
import logging
import os
import re
from datetime import timedelta
from pathlib import Path

from pyrogram.errors import FloodWait

from app.core.metrics import floodwait_seconds_hist, proxy_marked_unhealthy_total
from app.core.settings import get_settings
from app.core.tz import utcnow
from app.models.proxy import Proxy, ProxyStatus
from app.models.telegram_account import TelegramAccount, TelegramAccountStatus
from app.models.telegram_auth_flow import TelegramAuthFlow
from app.services.websocket_manager import manager

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Logging / sanitisation ───────────────────────────────────────────

def _mask_phone(phone: str) -> str:
    """Mask phone number for logging (no PII in logs).
    '+380501234567' -> '+380*****4567'
    """
    if not phone or len(phone) < 8:
        return "***"
    return phone[:4] + "*" * (len(phone) - 8) + phone[-4:]


_PHONE_RE = re.compile(r"\+\d{7,15}")


def _sanitize_error(msg: str) -> str:
    """Remove any phone numbers from error messages before logging."""
    return _PHONE_RE.sub("***", msg)


# ── WebSocket broadcasts ─────────────────────────────────────────────

def _broadcast_account_update(account: TelegramAccount) -> None:
    manager.broadcast_sync({
        "type": "account_status_changed",
        "user_id": account.owner_user_id,
        "account_id": account.id,
        "status": account.status.value if hasattr(account.status, "value") else str(account.status),
    })


def _broadcast_flow_update(flow: TelegramAuthFlow, account_id: int, owner_user_id: int) -> None:
    manager.broadcast_sync({
        "type": "auth_flow_updated",
        "user_id": owner_user_id,
        "account_id": account_id,
        "flow_id": flow.id,
        "state": flow.state.value if hasattr(flow.state, "value") else str(flow.state),
    })


# ── Error handling ───────────────────────────────────────────────────

def _handle_floodwait(account: TelegramAccount, exc: FloodWait, db) -> None:
    """Unified FloodWait handling: set cooldown + record metrics."""
    wait_s = int(exc.value)
    floodwait_seconds_hist.observe(wait_s)
    account.status = TelegramAccountStatus.cooldown
    account.cooldown_until = utcnow() + timedelta(seconds=wait_s)
    account.last_error = f"FloodWait: {wait_s}s"
    db.commit()


def _mark_proxy_unhealthy(proxy: Proxy | None, db) -> None:
    """Mark proxy as errored when it causes connection failures."""
    if proxy is None:
        return
    proxy.status = ProxyStatus.error
    proxy.last_check = utcnow()
    db.commit()
    proxy_marked_unhealthy_total.inc()


def _is_network_error(exc: Exception) -> bool:
    """Heuristic to identify network/timeout errors."""
    msg = str(exc).lower()
    return any(kw in msg for kw in ("timeout", "connection", "network", "eof", "reset", "refused"))


# ── Telegram client diagnostics ──────────────────────────────────────

def _log_client_fingerprint(log, ctx, client) -> None:
    """Log Telegram client session identity for cross-step consistency checks."""
    try:
        session_id = getattr(client, "name", None) or "unknown"
        proxy = getattr(client, "proxy", None) or {}
        if isinstance(proxy, dict):
            proxy_host = "%s:%s" % (proxy.get("hostname", "?"), proxy.get("port", "?"))
        else:
            proxy_host = "none"
        device_model = getattr(client, "device_model", "?")
        system_version = getattr(client, "system_version", "?")
        app_version = getattr(client, "app_version", "?")
        log.info(
            "event=telegram_client_fingerprint %s session=%s proxy=%s device=%s system=%s app=%s",
            ctx, session_id, proxy_host, device_model, system_version, app_version,
        )
    except Exception:
        log.warning("event=telegram_client_fingerprint_error %s", ctx)


# ── DC migration helpers ─────────────────────────────────────────────

async def _get_dc_id(client) -> str:
    """Extract dc_id from a connected Pyrogram client (best-effort)."""
    try:
        dc = client.storage.dc_id
        if callable(dc):
            dc_val = dc()
            if inspect.isawaitable(dc_val):
                dc_val = await dc_val
            return str(dc_val)
        return str(dc)
    except Exception:
        return "unknown"


async def _set_dc_id(client, dc_id: int) -> None:
    """Set dc_id on a Pyrogram client storage (sync/async safe)."""
    dc_val = client.storage.dc_id(dc_id)
    if inspect.isawaitable(dc_val):
        await dc_val


def _is_dc_migrate_error(exc: Exception) -> bool:
    return "MIGRATE" in type(exc).__name__.upper() or "MIGRATE" in str(exc).upper()


def _extract_migrate_dc(exc: Exception) -> int | None:
    dc = getattr(exc, "value", None)
    if isinstance(dc, int):
        return dc
    m = re.search(r"MIGRATE[_ ]*(\d+)", str(exc).upper())
    return int(m.group(1)) if m else None


# ── Pre-auth session persistence ─────────────────────────────────────
# File-based Pyrogram sessions persist auth_key between send_code and
# confirm_code Celery tasks, avoiding Telegram PhoneCodeExpired errors
# caused by creating a fresh auth_key on each task invocation.

_PRE_AUTH_DIR = Path(os.environ.get("PRE_AUTH_SESSION_DIR", "/data/pyrogram_pre_auth"))


def _pre_auth_session_name(flow_id: str) -> str:
    """Deterministic Pyrogram session name tied to auth flow."""
    return f"preauth-{flow_id}"


def _pre_auth_session_path(flow_id: str) -> Path:
    """Full path to the pre-auth SQLite session file."""
    return _PRE_AUTH_DIR / f"{_pre_auth_session_name(flow_id)}.session"


def _ensure_pre_auth_dir() -> None:
    """Create pre-auth session directory if it doesn't exist.

    Logs diagnostics and raises RuntimeError with an actionable message
    when the directory cannot be created or is not writable (e.g. the
    Docker named volume is not mounted).
    """
    _log = logger.getChild("pre_auth_dir")
    _log.info(
        "event=pre_auth_dir_check path=%s exists=%s",
        _PRE_AUTH_DIR, _PRE_AUTH_DIR.exists(),
    )
    try:
        _PRE_AUTH_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        _log.error(
            "event=pre_auth_dir_create_failed path=%s error=%s "
            "hint=ensure 'pre-auth-sessions' volume is mounted in docker-compose.prod.yml",
            _PRE_AUTH_DIR, exc,
        )
        raise RuntimeError(
            f"pre-auth dir not writable: cannot create {_PRE_AUTH_DIR} — "
            f"check that the 'pre-auth-sessions' named volume is mounted "
            f"at {_PRE_AUTH_DIR} in docker-compose.prod.yml"
        ) from exc

    if not os.access(_PRE_AUTH_DIR, os.W_OK):
        _log.error(
            "event=pre_auth_dir_not_writable path=%s "
            "hint=volume may be owned by root; container user must have write access",
            _PRE_AUTH_DIR,
        )
        raise RuntimeError(
            f"pre-auth dir not writable: {_PRE_AUTH_DIR} exists but is not writable — "
            f"check volume permissions for the container user"
        )


def _cleanup_pre_auth_session(flow_id: str, log=None) -> None:
    """Remove temporary pre-auth session file (and SQLite side-files)."""
    base = _pre_auth_session_path(flow_id)
    for suffix in ("", "-journal", "-wal", "-shm"):
        try:
            (base.parent / (base.name + suffix)).unlink(missing_ok=True)
        except Exception:
            pass
    if log:
        log.info("event=pre_auth_session_cleaned flow_id=%s", flow_id)


def _read_session_auth_key(session_path: Path, log=None) -> dict:
    """Read dc_id and auth_key from a Pyrogram SQLite session file.

    Returns dict with dc_id, auth_key_len, auth_key_prefix (first 8 bytes hex),
    or error info if the file is missing/corrupt.
    """
    import sqlite3

    result: dict = {"exists": False, "size": 0, "dc_id": None, "auth_key_len": 0, "auth_key_prefix": ""}
    try:
        if not session_path.exists():
            return result
        result["exists"] = True
        result["size"] = session_path.stat().st_size

        conn = sqlite3.connect(str(session_path))
        try:
            row = conn.execute("SELECT dc_id, auth_key FROM sessions").fetchone()
            if row:
                result["dc_id"] = row[0]
                auth_key = row[1] if row[1] else b""
                if isinstance(auth_key, bytes):
                    result["auth_key_len"] = len(auth_key)
                    result["auth_key_prefix"] = auth_key[:8].hex() if auth_key else ""
                else:
                    result["auth_key_len"] = len(str(auth_key))
                    result["auth_key_prefix"] = str(auth_key)[:16]
            else:
                result["dc_id"] = None
                result["auth_key_len"] = 0
                result["auth_key_prefix"] = "no_row"
        finally:
            conn.close()
    except Exception as exc:
        result["error"] = str(exc)[:200]
        if log:
            log.warning("event=read_session_auth_key_error path=%s error=%s", session_path, exc)
    return result
