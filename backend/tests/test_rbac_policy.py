"""Parameterized RBAC policy tests.

Every combination of resource / action / role is tested automatically
against ``app.core.rbac.POLICY``.  When POLICY changes, the test
parameters update with it — nothing is hard-coded.
"""

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.core.rbac import POLICY, require_permission
from app.models.user import UserRole


ALL_ROLES: list[str] = [r.value for r in UserRole]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_user(role: str) -> MagicMock:
    user = MagicMock()
    user.role = role
    return user


def _positive_cases() -> list[tuple[str, str, str]]:
    """Yield (resource, action, role) for every allowed combination."""
    cases = []
    for resource, actions in POLICY.items():
        for action, roles in actions.items():
            for role in roles:
                cases.append((resource, action, role))
    return cases


def _negative_cases() -> list[tuple[str, str, str]]:
    """Yield (resource, action, role) for every denied combination."""
    cases = []
    for resource, actions in POLICY.items():
        for action, allowed_roles in actions.items():
            denied = [r for r in ALL_ROLES if r not in allowed_roles]
            for role in denied:
                cases.append((resource, action, role))
    return cases


# ---------------------------------------------------------------------------
# Positive: allowed role → access granted
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "resource,action,role",
    _positive_cases(),
    ids=[f"{r}:{a}:{ro}" for r, a, ro in _positive_cases()],
)
def test_allowed_role_gets_access(resource: str, action: str, role: str):
    dep_fn = require_permission(resource, action)
    user = _make_user(role)
    result = dep_fn(current_user=user)
    assert result is user


# ---------------------------------------------------------------------------
# Negative: denied role → 403
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "resource,action,role",
    _negative_cases(),
    ids=[f"{r}:{a}:{ro}" for r, a, ro in _negative_cases()],
)
def test_denied_role_is_rejected(resource: str, action: str, role: str):
    dep_fn = require_permission(resource, action)
    user = _make_user(role)
    with pytest.raises(Exception, match="Access denied"):
        dep_fn(current_user=user)


# ---------------------------------------------------------------------------
# Edge: nonexistent resource → denied for all
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ALL_ROLES)
def test_nonexistent_resource_denied(role: str):
    dep_fn = require_permission("nonexistent_resource", "list")
    user = _make_user(role)
    with pytest.raises(Exception, match="Access denied"):
        dep_fn(current_user=user)


# ---------------------------------------------------------------------------
# Edge: nonexistent action → denied for all
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("role", ALL_ROLES)
def test_nonexistent_action_denied(role: str):
    first_resource = next(iter(POLICY))
    dep_fn = require_permission(first_resource, "nonexistent_action")
    user = _make_user(role)
    with pytest.raises(Exception, match="Access denied"):
        dep_fn(current_user=user)


# ---------------------------------------------------------------------------
# Edge: empty-string role → denied for every resource/action
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "resource,action",
    [
        (resource, action)
        for resource, actions in POLICY.items()
        for action in actions
    ],
    ids=[
        f"{r}:{a}"
        for r, actions in POLICY.items()
        for a in actions
    ],
)
def test_empty_role_denied(resource: str, action: str):
    dep_fn = require_permission(resource, action)
    user = _make_user("")
    with pytest.raises(Exception, match="Access denied"):
        dep_fn(current_user=user)


# ---------------------------------------------------------------------------
# Fail-loud: every require_permission() call in endpoints must exist in POLICY
# ---------------------------------------------------------------------------

_API_DIR = Path(__file__).resolve().parents[1] / "app" / "api"

_REQUIRE_PERM_RE = re.compile(r'require_permission\(\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\)')


def _collect_endpoint_permissions() -> list[tuple[str, str, str]]:
    """Scan all Python files under app/api/ for require_permission() calls."""
    results = []
    for py_file in _API_DIR.rglob("*.py"):
        source = py_file.read_text()
        for match in _REQUIRE_PERM_RE.finditer(source):
            resource, action = match.group(1), match.group(2)
            results.append((str(py_file.relative_to(_API_DIR.parent.parent)), resource, action))
    return results


_ENDPOINT_PERMISSIONS = _collect_endpoint_permissions()


@pytest.mark.parametrize(
    "filepath,resource,action",
    _ENDPOINT_PERMISSIONS,
    ids=[f"{fp}:{r}:{a}" for fp, r, a in _ENDPOINT_PERMISSIONS],
)
def test_endpoint_permission_exists_in_policy(filepath: str, resource: str, action: str):
    """Every require_permission(resource, action) used in an endpoint must
    have a corresponding entry in POLICY.  If this test fails, it means
    an endpoint references a resource/action pair that POLICY doesn't define,
    so ALL roles will be silently denied."""
    allowed = POLICY.get(resource, {}).get(action, [])
    assert allowed, (
        f"{filepath} uses require_permission(\"{resource}\", \"{action}\") "
        f"but POLICY has no entry for it — all roles are silently denied"
    )
