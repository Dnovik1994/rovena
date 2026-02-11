"""Timezone utilities.

MySQL DATETIME columns do not store timezone information.  PyMySQL therefore
returns *naive* ``datetime`` objects even when SQLAlchemy is told
``DateTime(timezone=True)``.  All application code uses UTC-aware datetimes
(``datetime.now(timezone.utc)``), so comparing them with naive DB values
triggers ``TypeError("can't compare offset-naive and offset-aware datetimes")``.

This module provides small helpers that normalise datetimes to UTC-aware before
any comparison or arithmetic.
"""

from __future__ import annotations

from datetime import datetime, timezone


def ensure_utc(dt: datetime | None) -> datetime | None:
    """Return *dt* as a UTC-aware datetime.

    * If *dt* is ``None`` — return ``None``.
    * If *dt* is already offset-aware — return as-is.
    * If *dt* is naive — assume it represents UTC and attach ``timezone.utc``.
    """
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def utcnow() -> datetime:
    """Shortcut for ``datetime.now(timezone.utc)``."""
    return datetime.now(timezone.utc)
