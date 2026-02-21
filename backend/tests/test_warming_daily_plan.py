"""Tests for _get_daily_plan — day-based warming plan generation."""

from unittest.mock import MagicMock, patch

import pytest

from app.workers.tg_warming_tasks import _get_daily_plan


@pytest.fixture()
def account():
    acc = MagicMock()
    acc.id = 1
    acc.phone_e164 = "+380501234567"
    return acc


@pytest.fixture()
def db():
    return MagicMock()


# ── Day 0: rest period ──────────────────────────────────────────────


def test_day_0_returns_empty(account, db):
    """Day 0 (отлёжка) — no actions."""
    plan = _get_daily_plan(0, account, db)
    assert plan == []


# ── Day 1: go_online + set_photo ────────────────────────────────────


def test_day_1_has_go_online_and_set_photo(account, db):
    """Day 1 must contain exactly go_online and set_photo."""
    plan = _get_daily_plan(1, account, db)
    actions = [step["action"] for step in plan]
    assert actions == ["go_online", "set_photo"]


# ── Day 3: trusted_conversation ─────────────────────────────────────


def test_day_3_has_trusted_conversation(account, db):
    """Day 3 must include trusted_conversation."""
    plan = _get_daily_plan(3, account, db)
    actions = [step["action"] for step in plan]
    assert "go_online" in actions
    assert "trusted_conversation" in actions
    assert "send_saved_message" in actions


# ── Day 8: set_username ─────────────────────────────────────────────


def test_day_8_has_set_username(account, db):
    """Day 8 must include set_username."""
    plan = _get_daily_plan(8, account, db)
    actions = [step["action"] for step in plan]
    assert "set_username" in actions
    assert "go_online" in actions


# ── Day 12: set_name ────────────────────────────────────────────────


def test_day_12_has_set_name(account, db):
    """Day 12 must include set_name."""
    plan = _get_daily_plan(12, account, db)
    actions = [step["action"] for step in plan]
    assert "set_name" in actions
    assert "go_online" in actions


# ── Day 14+: full cycle ─────────────────────────────────────────────


def test_day_14_plus_full_cycle(account, db):
    """Day 14+ returns a full plan with go_online, read, react, join, saved."""
    plan = _get_daily_plan(14, account, db)
    actions = [step["action"] for step in plan]
    assert actions[0] == "go_online"
    assert "read_channels" in actions
    assert "react" in actions
    assert "join_channels" in actions
    assert "send_saved_message" in actions


def test_day_20_uses_same_plan_as_14(account, db):
    """Any day >= 14 uses the same full-cycle template."""
    plan = _get_daily_plan(20, account, db)
    actions = [step["action"] for step in plan]
    assert actions[0] == "go_online"
    assert "read_channels" in actions
    assert "react" in actions
    assert "send_saved_message" in actions


# ── Every day (except 0) starts with go_online ──────────────────────


def test_all_days_have_go_online(account, db):
    """Every day from 1 to 15 must start with go_online."""
    for day in range(1, 16):
        plan = _get_daily_plan(day, account, db)
        assert len(plan) > 0, f"Day {day} returned empty plan"
        assert plan[0]["action"] == "go_online", (
            f"Day {day} does not start with go_online: {plan[0]}"
        )


# ── Randomization ───────────────────────────────────────────────────


def test_plan_randomization(account, db):
    """Two calls for day 6 can produce different react counts (randomized)."""
    # Collect several plans and check that at least some have different
    # react counts — day 6 uses random.randint(1, 2) for react count.
    react_counts = set()
    for _ in range(50):
        plan = _get_daily_plan(6, account, db)
        for step in plan:
            if step["action"] == "react":
                react_counts.add(step["params"]["count"])
    # With 50 iterations, we should see both 1 and 2
    assert len(react_counts) > 1, (
        f"Expected randomization in react count, got only {react_counts}"
    )


# ── Structural checks for intermediate days ─────────────────────────


def test_day_2_has_add_contacts(account, db):
    """Day 2 must include add_contacts."""
    plan = _get_daily_plan(2, account, db)
    actions = [step["action"] for step in plan]
    assert actions == ["go_online", "add_contacts"]


def test_day_4_has_join_and_read_channels(account, db):
    """Day 4 has join_channels and read_channels."""
    plan = _get_daily_plan(4, account, db)
    actions = [step["action"] for step in plan]
    assert "go_online" in actions
    assert "join_channels" in actions
    assert "read_channels" in actions


def test_day_5_has_set_bio(account, db):
    """Day 5 includes set_bio."""
    plan = _get_daily_plan(5, account, db)
    actions = [step["action"] for step in plan]
    assert "set_bio" in actions


def test_day_9_no_set_username(account, db):
    """Day 9 should NOT have set_username (only day 8 does)."""
    plan = _get_daily_plan(9, account, db)
    actions = [step["action"] for step in plan]
    assert "set_username" not in actions


def test_day_13_no_set_name(account, db):
    """Day 13 should NOT have set_name (only day 12 does)."""
    plan = _get_daily_plan(13, account, db)
    actions = [step["action"] for step in plan]
    assert "set_name" not in actions


def test_day_6_7_have_join_groups(account, db):
    """Days 6-7 include join_groups."""
    for day in (6, 7):
        plan = _get_daily_plan(day, account, db)
        actions = [step["action"] for step in plan]
        assert "join_groups" in actions, f"Day {day} missing join_groups"
