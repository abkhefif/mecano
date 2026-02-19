"""Add performance indexes for common queries

Revision ID: 019
Revises: 018
Create Date: 2026-02-15 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "019"
down_revision: Union[str, None] = "018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    # AUD-C03: ix_notification_user_read and ix_dispute_status removed because
    # migration 015 already created equivalent indexes:
    #   - ix_dispute_cases_status on dispute_cases.status
    #   - ix_notifications_user_unread on notifications(user_id, is_read, created_at DESC)
    op.create_index("ix_availability_date", "availabilities", ["date"])

def downgrade() -> None:
    op.drop_index("ix_availability_date", table_name="availabilities")
