"""Add photo_urls column to dispute_cases table

Revision ID: 013
Revises: 012
Create Date: 2026-02-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "dispute_cases",
        sa.Column("photo_urls", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("dispute_cases", "photo_urls")
