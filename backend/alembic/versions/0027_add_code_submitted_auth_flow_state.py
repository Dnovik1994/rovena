"""Add code_submitted value to authflowstate enum.

Needed for unified_auth_task which polls DB for submitted codes.

Revision ID: 0027_add_code_submitted_auth_flow_state
Revises: 0026_add_warming_lease_fields
Create Date: 2026-02-17 00:00:00.000000
"""

from alembic import op

revision = "0027_add_code_submitted_auth_flow_state"
down_revision = "0026_add_warming_lease_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE authflowstate ADD VALUE IF NOT EXISTS 'code_submitted' AFTER 'wait_code'")


def downgrade() -> None:
    # PostgreSQL does not support removing values from an enum type.
    # The value is harmless if left in place after downgrade.
    pass
