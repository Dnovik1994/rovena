"""Tests for warming helpers (quiet hours, settings)."""

from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.workers.tg_warming_helpers import is_quiet_hours


def test_quiet_hours_inside(monkeypatch):
    """is_quiet_hours returns True when current hour falls in quiet range."""
    fake_now = datetime(2025, 1, 15, 3, 0, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
    with patch("app.workers.tg_warming_helpers.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert is_quiet_hours() is True


def test_quiet_hours_outside(monkeypatch):
    """is_quiet_hours returns False when current hour is outside quiet range."""
    fake_now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
    with patch("app.workers.tg_warming_helpers.datetime") as mock_dt:
        mock_dt.now.return_value = fake_now
        assert is_quiet_hours() is False
