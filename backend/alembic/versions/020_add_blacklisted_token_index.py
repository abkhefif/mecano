"""Add index on blacklisted_tokens.expires_at for cleanup queries

Revision ID: 020
Revises: 019
Create Date: 2026-02-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "020"
down_revision: Union[str, None] = "019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # F-023: Index to speed up the daily cleanup_expired_blacklisted_tokens cron
    # and the per-request blacklist check in dependencies.get_current_user.
    op.create_index("ix_blacklisted_tokens_expires_at", "blacklisted_tokens", ["expires_at"])

def downgrade() -> None:
    op.drop_index("ix_blacklisted_tokens_expires_at", table_name="blacklisted_tokens")
