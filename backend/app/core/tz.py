"""Timezone utilities — single source of truth for datetime handling.

MySQL DATETIME columns do not store timezone information.  PyMySQL therefore
returns *naive* ``datetime`` objects even when SQLAlchemy is told
``DateTime(timezone=True)``.  All application code uses UTC-aware datetimes
(``datetime.now(timezone.utc)``), so comparing them with naive DB values
triggers ``TypeError("can't compare offset-naive and offset-aware datetimes")``.

Convention:
    * All values stored in MySQL are **UTC-naive** (UTC time without tzinfo).
    * All values in application code are **UTC-aware**.
    * Use :func:`ensure_utc` when reading from DB, :func:`utcnow` for "now".
    * Use :func:`is_expired` for any expiry / cooldown comparison.
"""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Return *dt* as a UTC-aware datetime.

    * If *dt* is ``None`` — return ``None``.
    * If *dt* is naive — assume it represents UTC and attach ``timezone.utc``.
    * If *dt* is already UTC-aware — return as-is (same object).
    * If *dt* is aware but non-UTC — convert to UTC via ``astimezone``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    if dt.tzinfo is timezone.utc:
        return dt
    return dt.astimezone(timezone.utc)


def utcnow() -> datetime:
    """Shortcut for ``datetime.now(timezone.utc)``."""
    return datetime.now(timezone.utc)


def is_expired(expires_at: datetime | None, now: datetime | None = None) -> bool:
    """Check whether *expires_at* is in the past.

    Handles naive datetimes from MySQL transparently.
    Returns ``False`` when *expires_at* is ``None`` (no expiry set).
    """
    if expires_at is None:
        return False
    expires_at = ensure_utc(expires_at)
    if now is None:
        now = utcnow()
    return expires_at <= now
