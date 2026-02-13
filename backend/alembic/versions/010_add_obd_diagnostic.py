"""Add has_obd_diagnostic to mechanic_profiles

Revision ID: 010
Revises: 009
Create Date: 2026-02-11 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "mechanic_profiles",
        sa.Column("has_obd_diagnostic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("mechanic_profiles", "has_obd_diagnostic")
