"""Add missing booking columns and widen check_in_code for hashes

refuse_reason and proposed_time exist in the model but have no migration.
check_in_code needs to be widened from String(4) to String(64) for SHA-256 hashes.

Revision ID: 033
Revises: 032
Create Date: 2026-02-22
"""

from alembic import op
import sqlalchemy as sa

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add missing columns
    op.add_column("bookings", sa.Column("refuse_reason", sa.String(30), nullable=True))
    op.add_column("bookings", sa.Column("proposed_time", sa.String(5), nullable=True))

    # Widen check_in_code from String(4) to String(64) for SHA-256 hashes
    op.alter_column(
        "bookings",
        "check_in_code",
        type_=sa.String(64),
        existing_type=sa.String(4),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "bookings",
        "check_in_code",
        type_=sa.String(4),
        existing_type=sa.String(64),
        existing_nullable=True,
    )
    op.drop_column("bookings", "proposed_time")
    op.drop_column("bookings", "refuse_reason")
