"""Add api_app_id FK column to telegram_accounts

Links each Telegram account to a specific API app registered in
telegram_api_apps.  The column is nullable so existing rows are
unaffected.

Revision ID: 0022b_add_telegram_account_api_app_link
Revises: 0022_add_telegram_api_apps
Create Date: 2026-02-15 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0022b_add_telegram_account_api_app_link"
down_revision = "0022_add_telegram_api_apps"
branch_labels = None
depends_on = None

_FK_NAME = "fk_telegram_accounts_api_app_id"


def _column_exists(table: str, column: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    columns = [c["name"] for c in inspector.get_columns(table)]
    return column in columns


def _fk_exists(table: str, fk_name: str) -> bool:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    return fk_name in {fk["name"] for fk in inspector.get_foreign_keys(table)}


def upgrade() -> None:
    if not _column_exists("telegram_accounts", "api_app_id"):
        op.add_column(
            "telegram_accounts",
            sa.Column("api_app_id", sa.Integer(), nullable=True),
        )
    if not _fk_exists("telegram_accounts", _FK_NAME):
        op.create_foreign_key(
            _FK_NAME,
            "telegram_accounts",
            "telegram_api_apps",
            ["api_app_id"],
            ["id"],
        )


def downgrade() -> None:
    op.drop_constraint(_FK_NAME, "telegram_accounts", type_="foreignkey")
    op.drop_column("telegram_accounts", "api_app_id")
