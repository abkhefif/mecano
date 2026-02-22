"""Add composite indexes on bookings (buyer_id, created_at) and (mechanic_id, created_at)

Revision ID: 016
Revises: 015
Create Date: 2026-02-13 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = "016"
down_revision: Union[str, None] = "015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Composite index for buyer listing queries (ordered by created_at)
    try:
        op.create_index(
            "ix_booking_buyer_created",
            "bookings",
            ["buyer_id", "created_at"],
        )
    except Exception as e:
        import logging
        logging.getLogger("alembic").info(f"Index ix_booking_buyer_created may already exist: {e}")

    # Composite index for mechanic listing queries (ordered by created_at)
    try:
        op.create_index(
            "ix_booking_mechanic_created",
            "bookings",
            ["mechanic_id", "created_at"],
        )
    except Exception as e:
        import logging
        logging.getLogger("alembic").info(f"Index ix_booking_mechanic_created may already exist: {e}")


def downgrade() -> None:
    op.drop_index("ix_booking_mechanic_created", table_name="bookings")
    op.drop_index("ix_booking_buyer_created", table_name="bookings")
