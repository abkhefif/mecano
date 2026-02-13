"""Add index on reviews.booking_id (model alignment)

The reviews.booking_id index (ix_reviews_booking_id) was already created at the
database level in migration 006.  This migration synchronises the SQLAlchemy
model declaration (index=True on the booking_id column) and uses
if_not_exists so it is safe to run even when 006 has already been applied.

Revision ID: 007
Revises: 006
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create index idempotently – migration 006 may have already created it.
    op.create_index(
        "ix_reviews_booking_id",
        "reviews",
        ["booking_id"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_reviews_booking_id", table_name="reviews", if_exists=True)
