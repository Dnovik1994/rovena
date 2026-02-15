from collections.abc import Callable

from fastapi import Depends

from app.api.deps import get_current_active_user
from app.core.errors import forbidden
from app.models.user import User

POLICY: dict[str, dict[str, list[str]]] = {
    "proxies": {
        "list": ["admin", "superadmin"],
        "create": ["admin", "superadmin"],
        "update": ["admin", "superadmin"],
        "delete": ["admin", "superadmin"],
        "validate": ["admin", "superadmin"],
    },
    "accounts": {
        "list": ["user", "admin", "superadmin"],
        "create": ["user", "admin", "superadmin"],
        "update": ["user", "admin", "superadmin"],
        "delete": ["user", "admin", "superadmin"],
        "start_warming": ["user", "admin", "superadmin"],
        "verify": ["user", "admin", "superadmin"],
    },
    "tg_accounts": {
        "list": ["user", "admin", "superadmin"],
        "create": ["user", "admin", "superadmin"],
        "update": ["user", "admin", "superadmin"],
        "delete": ["user", "admin", "superadmin"],
        "send_code": ["user", "admin", "superadmin"],
        "confirm_code": ["user", "admin", "superadmin"],
        "confirm_password": ["user", "admin", "superadmin"],
        "disconnect": ["user", "admin", "superadmin"],
        "health_check": ["user", "admin", "superadmin"],
        "verify": ["user", "admin", "superadmin"],
        "warmup": ["user", "admin", "superadmin"],
        "regenerate_device": ["user", "admin", "superadmin"],
        "assign_resources": ["user", "admin", "superadmin"],
    },
    "api_apps": {
        "list": ["admin", "superadmin"],
        "create": ["admin", "superadmin"],
        "update": ["admin", "superadmin"],
        "delete": ["admin", "superadmin"],
    },
    "users": {
        "list": ["admin", "superadmin"],
    },
}


def require_permission(resource: str, action: str) -> Callable:
    allowed_roles = POLICY.get(resource, {}).get(action, [])

    def _dependency(current_user: User = Depends(get_current_active_user)) -> User:
        if current_user.role not in allowed_roles:
            raise forbidden("Access denied")
        return current_user

    return _dependency
