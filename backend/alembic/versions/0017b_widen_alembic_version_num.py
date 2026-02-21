"""widen alembic_version.version_num for long revision IDs

Revision ID: 0017b_widen_alembic_version_num
Revises: 0017_add_performance_indexes
Create Date: 2026-02-11 00:00:00.000000
"""

from alembic import op
from sqlalchemy import inspect as sa_inspect

revision = "0017b_widen_alembic_version_num"
down_revision = "0017_add_performance_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "mysql":
        return

    inspector = sa_inspect(bind)
    if "alembic_version" not in inspector.get_table_names():
        return

    columns = {col["name"]: col for col in inspector.get_columns("alembic_version")}
    version_col = columns.get("version_num")
    current_length = getattr(version_col.get("type"), "length", None) if version_col else None

    if current_length is None or current_length < 128:
        op.execute("ALTER TABLE alembic_version MODIFY version_num VARCHAR(128) NOT NULL")


def downgrade() -> None:
    # Do not shrink column to avoid data truncation.
    pass
