"""Add password_changed_at column to users table

SEC-005: Track when a user last changed their password so that all tokens
issued before that timestamp can be rejected. This invalidates all active
sessions across all devices when a password is changed.

Revision ID: 025
Revises: 024
Create Date: 2026-02-17 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "025"
down_revision: Union[str, None] = "024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("password_changed_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "password_changed_at")
