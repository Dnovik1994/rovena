"""add account warming fields

Revision ID: 0007
Revises: 0006
Create Date: 2024-10-11 01:35:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "warming_actions_completed" not in columns:
        op.add_column(
            "accounts",
            sa.Column(
                "warming_actions_completed",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        op.alter_column("accounts", "warming_actions_completed", server_default=None)

    if "target_warming_actions" not in columns:
        op.add_column(
            "accounts",
            sa.Column(
                "target_warming_actions",
                sa.Integer(),
                nullable=False,
                server_default="10",
            ),
        )
        op.alter_column("accounts", "target_warming_actions", server_default=None)

    if "cooldown_until" not in columns:
        op.add_column(
            "accounts",
            sa.Column("cooldown_until", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "cooldown_until" in columns:
        op.drop_column("accounts", "cooldown_until")
    if "target_warming_actions" in columns:
        op.drop_column("accounts", "target_warming_actions")
    if "warming_actions_completed" in columns:
        op.drop_column("accounts", "warming_actions_completed")
