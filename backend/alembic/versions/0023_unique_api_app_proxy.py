"""Add unique constraint on (api_app_id, proxy_id) in telegram_accounts.

Two accounts sharing the same API app and the same proxy means identical
(api_id + IP) from Telegram's perspective — a red flag for anti-ban.
The DB-level constraint guarantees this can never happen, even if the
application-level check in assign_api_app is bypassed.

Revision ID: 0023_unique_api_app_proxy
Revises: 0022_add_telegram_api_apps
Create Date: 2026-02-15 00:00:00.000000
"""

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0023_unique_api_app_proxy"
down_revision = "0022_add_telegram_api_apps"
branch_labels = None
depends_on = None

_CONSTRAINT_NAME = "uq_tg_accounts_api_app_proxy"


def _constraint_exists() -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    for uq in inspector.get_unique_constraints("telegram_accounts"):
        if uq["name"] == _CONSTRAINT_NAME:
            return True
    return False


def upgrade() -> None:
    if _constraint_exists():
        return
    op.create_unique_constraint(
        _CONSTRAINT_NAME,
        "telegram_accounts",
        ["api_app_id", "proxy_id"],
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT_NAME, "telegram_accounts", type_="unique")
