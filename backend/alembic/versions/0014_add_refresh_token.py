"""add refresh token to users

Revision ID: 0014_add_refresh_token
Revises: 0013
Create Date: 2025-09-20 00:00:00.000000
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect as sa_inspect


# revision identifiers, used by Alembic.
revision = "0014_add_refresh_token"
down_revision = "0013"
branch_labels = None
depends_on = None


def _column_exists(table: str, column: str) -> bool:
    if context.is_offline_mode():
        return False
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return column in {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    if not _column_exists("users", "refresh_token"):
        op.add_column("users", sa.Column("refresh_token", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "refresh_token")
