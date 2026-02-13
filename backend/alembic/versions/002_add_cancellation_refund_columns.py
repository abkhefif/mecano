"""Add cancellation and refund columns to bookings

Revision ID: 002
Revises: 001
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("cancelled_by", sa.String(10), nullable=True))
    op.add_column("bookings", sa.Column("refund_percentage", sa.Integer(), nullable=True))
    op.add_column("bookings", sa.Column("refund_amount", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("bookings", "refund_amount")
    op.drop_column("bookings", "refund_percentage")
    op.drop_column("bookings", "cancelled_by")
