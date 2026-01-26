"""add default device config

Revision ID: 0008
Revises: 0007
Create Date: 2024-10-11 02:20:00
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "device_config" in columns:
        default_config = (
            '{"app_version":"10.5.0","system_version":"Android 13",'
            '"device_model":"Pixel 6","lang_code":"en"}'
        )
        op.alter_column("accounts", "device_config", server_default=sa.text(f"'{default_config}'"))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("accounts")}

    if "device_config" in columns:
        op.alter_column("accounts", "device_config", server_default=None)
