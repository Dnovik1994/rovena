"""add verified status and proxy latency

Revision ID: 0011
Revises: 0010
Create Date: 2024-10-12 03:20:00
"""

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if context.is_offline_mode():
        proxy_columns = set()
        dialect_name = context.get_context().dialect.name
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        proxy_columns = {column["name"] for column in inspector.get_columns("proxies")}
        dialect_name = bind.dialect.name

    if "latency_ms" not in proxy_columns:
        op.add_column("proxies", sa.Column("latency_ms", sa.Integer(), nullable=True))

    if dialect_name == "mysql":
        op.execute(
            "ALTER TABLE accounts MODIFY COLUMN status "
            "ENUM('new','warming','active','cooldown','blocked','verified') NOT NULL"
        )


def downgrade() -> None:
    if context.is_offline_mode():
        proxy_columns = {"latency_ms"}
        dialect_name = context.get_context().dialect.name
    else:
        bind = op.get_bind()
        inspector = inspect(bind)
        proxy_columns = {column["name"] for column in inspector.get_columns("proxies")}
        dialect_name = bind.dialect.name

    if "latency_ms" in proxy_columns:
        op.drop_column("proxies", "latency_ms")

    if dialect_name == "mysql":
        op.execute(
            "ALTER TABLE accounts MODIFY COLUMN status "
            "ENUM('new','warming','active','cooldown','blocked') NOT NULL"
        )
