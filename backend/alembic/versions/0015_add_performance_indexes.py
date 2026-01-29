"""add performance indexes

Revision ID: 0015_add_performance_indexes
Revises: 0014_add_refresh_token
Create Date: 2025-09-20 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision = "0015_add_performance_indexes"
down_revision = "0014_add_refresh_token"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_tariff_id ON users (tariff_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_accounts_status ON accounts (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_campaigns_status ON campaigns (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_proxies_status ON proxies (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_blocked ON contacts (blocked)")


def downgrade() -> None:
    op.drop_index("ix_contacts_blocked", table_name="contacts")
    op.drop_index("ix_proxies_status", table_name="proxies")
    op.drop_index("ix_campaigns_status", table_name="campaigns")
    op.drop_index("ix_accounts_status", table_name="accounts")
    op.drop_index("ix_users_tariff_id", table_name="users")
