"""add refresh token to users

Revision ID: 0014_add_refresh_token
Revises: 0013_add_tariff_system
Create Date: 2025-09-20 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0014_add_refresh_token"
down_revision = "0013_add_tariff_system"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("refresh_token", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "refresh_token")
