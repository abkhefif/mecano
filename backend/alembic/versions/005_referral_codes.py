"""Add referral codes table and referred_by column

Revision ID: 005
Revises: 004
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create referral_codes table
    op.create_table(
        "referral_codes",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(20), unique=True, nullable=False, index=True),
        sa.Column("mechanic_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("mechanic_profiles.id"), nullable=False, unique=True),
        sa.Column("uses_count", sa.Integer(), nullable=False, default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Add referred_by column to mechanic_profiles
    op.add_column("mechanic_profiles", sa.Column("referred_by", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("mechanic_profiles", "referred_by")
    op.drop_table("referral_codes")
