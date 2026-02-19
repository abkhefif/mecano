"""Add additional_photo_urls JSON column to validation_proofs table

Revision ID: 017
Revises: 016
Create Date: 2026-02-15 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "017"
down_revision: Union[str, None] = "016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "validation_proofs",
        sa.Column("additional_photo_urls", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("validation_proofs", "additional_photo_urls")
