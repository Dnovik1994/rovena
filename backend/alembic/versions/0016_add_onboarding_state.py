"""add onboarding state to users

Revision ID: 0016_add_onboarding_state
Revises: 0015_add_performance_indexes
Create Date: 2025-09-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0016_add_onboarding_state"
down_revision = "0015_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("users", "onboarding_completed", server_default=None)


def downgrade() -> None:
    op.drop_column("users", "onboarding_completed")
