"""Add indexes on sender_id, dispute status, reviewer_id, notifications composite; CASCADE FK on messages.sender_id; CHECK on dispute status

Revision ID: 015
Revises: 014
Create Date: 2026-02-12 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Index on messages.sender_id
    op.create_index("ix_messages_sender_id", "messages", ["sender_id"])

    # Index on dispute_cases.status
    op.create_index("ix_dispute_cases_status", "dispute_cases", ["status"])

    # Index on reviews.reviewer_id
    op.create_index("ix_reviews_reviewer_id", "reviews", ["reviewer_id"])

    # Composite index on notifications (user_id, is_read, created_at DESC)
    op.create_index(
        "ix_notifications_user_unread",
        "notifications",
        ["user_id", "is_read", sa.text("created_at DESC")],
    )

    # Drop old FK on messages.sender_id and recreate with ondelete CASCADE
    op.drop_constraint("messages_sender_id_fkey", "messages", type_="foreignkey")
    op.create_foreign_key(
        "messages_sender_id_fkey",
        "messages",
        "users",
        ["sender_id"],
        ["id"],
        ondelete="CASCADE",
    )

    # CHECK constraint on dispute_cases.status
    op.create_check_constraint(
        "ck_dispute_cases_status_valid",
        "dispute_cases",
        "status IN ('open', 'resolved_buyer', 'resolved_mechanic', 'closed')",
    )


def downgrade() -> None:
    # Reverse CHECK constraint
    op.drop_constraint("ck_dispute_cases_status_valid", "dispute_cases", type_="check")

    # Reverse FK CASCADE — recreate without ondelete
    op.drop_constraint("messages_sender_id_fkey", "messages", type_="foreignkey")
    op.create_foreign_key(
        "messages_sender_id_fkey",
        "messages",
        "users",
        ["sender_id"],
        ["id"],
    )

    # Reverse composite index on notifications
    op.drop_index("ix_notifications_user_unread", table_name="notifications")

    # Reverse index on reviews.reviewer_id
    op.drop_index("ix_reviews_reviewer_id", table_name="reviews")

    # Reverse index on dispute_cases.status
    op.drop_index("ix_dispute_cases_status", table_name="dispute_cases")

    # Reverse index on messages.sender_id
    op.drop_index("ix_messages_sender_id", table_name="messages")
