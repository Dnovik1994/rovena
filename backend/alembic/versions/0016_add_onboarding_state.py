"""add onboarding state to users

Revision ID: 0016_add_onboarding_state
Revises: 0015_add_performance_indexes
Create Date: 2025-09-20 00:00:00.000000
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision = "0016_add_onboarding_state"
down_revision = "0015_add_performance_indexes"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("users", "onboarding_completed"):
        op.add_column(
            "users",
            sa.Column("onboarding_completed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.alter_column("users", "onboarding_completed", server_default=None)


def downgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(sa.text(
        "SELECT COUNT(*) FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' "
        "AND COLUMN_NAME = 'onboarding_completed'"
    )).scalar()
    if exists:
        op.drop_column("users", "onboarding_completed")
