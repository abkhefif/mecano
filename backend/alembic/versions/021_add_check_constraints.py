"""Add CHECK constraints for cancelled_by and notification type

R-003: Booking.cancelled_by must be 'buyer', 'mechanic', or NULL
R-004: Notification.type must be a valid NotificationType enum value

Revision ID: 021
Revises: 020
Create Date: 2026-02-16 00:00:00.000000
"""
from typing import Sequence, Union
from alembic import op

revision: str = "021"
down_revision: Union[str, None] = "020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # R-003: Restrict cancelled_by to valid values
    # I-001: Migration 014 already created constraint 'ck_booking_cancelled_by_valid'
    # with the same expression. Wrap in try/except to make idempotent on fresh PG
    # where both migrations run (two constraints with different names are harmless,
    # but some databases may reject duplicates).
    try:
        op.create_check_constraint(
            "ck_booking_cancelled_by",
            "bookings",
            "cancelled_by IN ('buyer', 'mechanic') OR cancelled_by IS NULL",
        )
    except Exception as e:
        import logging
        logging.getLogger("alembic").info(f"Constraint ck_booking_cancelled_by may already exist: {e}")

    # R-004: Restrict notification type to valid enum values
    try:
        op.create_check_constraint(
            "ck_notification_type",
            "notifications",
            "type IN ("
            "'booking_created', 'booking_confirmed', 'booking_refused', "
            "'booking_cancelled', 'check_out_done', 'booking_disputed', "
            "'new_message', 'reminder', 'no_show', 'profile_verification'"
            ")",
        )
    except Exception as e:
        import logging
        logging.getLogger("alembic").info(f"Constraint ck_notification_type may already exist: {e}")


def downgrade() -> None:
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.drop_constraint("ck_booking_cancelled_by", "bookings", type_="check")
