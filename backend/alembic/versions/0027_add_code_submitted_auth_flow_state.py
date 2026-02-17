"""Add code_submitted value to authflowstate enum.

Needed for unified_auth_task which polls DB for submitted codes.

Revision ID: 0027_add_code_submitted_auth_flow_state
Revises: 0026_add_warming_lease_fields
Create Date: 2026-02-17 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "0027_add_code_submitted_auth_flow_state"
down_revision = "0026_add_warming_lease_fields"
branch_labels = None
depends_on = None

_NEW_ENUM = sa.Enum(
    "init", "code_sent", "wait_code", "code_submitted",
    "wait_password", "done", "expired", "failed",
    name="authflowstate",
)
_OLD_ENUM = sa.Enum(
    "init", "code_sent", "wait_code",
    "wait_password", "done", "expired", "failed",
    name="authflowstate",
)


def upgrade() -> None:
    op.alter_column(
        "telegram_auth_flows",
        "state",
        type_=_NEW_ENUM,
        existing_type=_OLD_ENUM,
        existing_nullable=False,
        existing_server_default="init",
    )


def downgrade() -> None:
    op.alter_column(
        "telegram_auth_flows",
        "state",
        type_=_OLD_ENUM,
        existing_type=_NEW_ENUM,
        existing_nullable=False,
        existing_server_default="init",
    )
