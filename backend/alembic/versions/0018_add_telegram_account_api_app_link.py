"""add telegram_account api_app_id FK

Revision ID: 0018_add_telegram_account_api_app_link
Revises: 0017_add_performance_indexes
Create Date: 2026-02-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0018_add_telegram_account_api_app_link"
down_revision = "0017_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "telegram_accounts",
        sa.Column("api_app_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_telegram_accounts_api_app_id",
        "telegram_accounts",
        "telegram_api_apps",
        ["api_app_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_telegram_accounts_api_app_id", "telegram_accounts", type_="foreignkey")
    op.drop_column("telegram_accounts", "api_app_id")
