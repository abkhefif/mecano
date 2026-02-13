"""Add reminder columns to bookings

Revision ID: 003
Revises: 002
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("bookings", sa.Column("reminder_24h_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("bookings", sa.Column("reminder_2h_sent", sa.Boolean(), nullable=False, server_default=sa.text("false")))


def downgrade() -> None:
    op.drop_column("bookings", "reminder_2h_sent")
    op.drop_column("bookings", "reminder_24h_sent")
