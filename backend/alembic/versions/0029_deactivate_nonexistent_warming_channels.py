"""Deactivate warming channels that may not exist on Telegram.

Sets is_active=0 for channels whose existence could not be verified.

Revision ID: 0029_deactivate_nonexistent_warming_channels
Revises: 0028_add_parsing_and_invite_system
Create Date: 2026-02-17 06:00:00.000000
"""

from alembic import op
from sqlalchemy import inspect as sa_inspect, text

revision = "0029_deactivate_nonexistent_warming_channels"
down_revision = "0028_add_parsing_and_invite_system"
branch_labels = None
depends_on = None

_SUSPECT_CHANNELS = [
    "unaborisfen",
    "teleaborisfen",
    "maborisfen",
    "taborisfen_chat",
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if "warming_channels" not in inspector.get_table_names():
        return

    for username in _SUSPECT_CHANNELS:
        op.execute(
            text(
                "UPDATE warming_channels SET is_active = 0 "
                "WHERE username = :u AND is_active = 1"
            ).bindparams(u=username)
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa_inspect(bind)
    if "warming_channels" not in inspector.get_table_names():
        return

    for username in _SUSPECT_CHANNELS:
        op.execute(
            text(
                "UPDATE warming_channels SET is_active = 1 "
                "WHERE username = :u"
            ).bindparams(u=username)
        )
