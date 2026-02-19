"""Add composite index on bookings(status, updated_at)

PERF-005: The scheduler queries frequently filter on (status, updated_at)
combinations, e.g. release_overdue_payments filters
status='validated' AND updated_at < cutoff. The single-column index on
status alone requires a secondary sort/filter on updated_at. This
composite index serves these queries directly.

Revision ID: 027
Revises: 026
Create Date: 2026-02-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "027"
down_revision: Union[str, None] = "026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_booking_status_updated",
        "bookings",
        ["status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_booking_status_updated", table_name="bookings")
