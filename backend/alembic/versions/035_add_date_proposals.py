"""Add date_proposals table and update notification type check constraint

Revision ID: 035
Revises: 034
Create Date: 2026-02-24
"""

import sqlalchemy as sa

from alembic import op

revision = "035"
down_revision = "034"


def upgrade() -> None:
    op.create_table(
        "date_proposals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("buyer_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("mechanic_id", sa.String(36), sa.ForeignKey("mechanic_profiles.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("proposed_date", sa.Date, nullable=False),
        sa.Column("proposed_time", sa.String(5), nullable=False),
        sa.Column("message", sa.Text, nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("round_number", sa.Integer, nullable=False, server_default="1"),
        sa.Column("parent_id", sa.String(36), sa.ForeignKey("date_proposals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("responded_by", sa.String(10), nullable=True),
        sa.Column("booking_id", sa.String(36), sa.ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("vehicle_brand", sa.String(100), nullable=False),
        sa.Column("vehicle_model", sa.String(100), nullable=False),
        sa.Column("vehicle_year", sa.Integer, nullable=False),
        sa.Column("vehicle_plate", sa.String(20), nullable=True),
        sa.Column("meeting_address", sa.Text, nullable=False),
        sa.Column("meeting_lat", sa.Numeric(9, 6), nullable=False),
        sa.Column("meeting_lng", sa.Numeric(9, 6), nullable=False),
        sa.Column("obd_requested", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )

    # Check constraints
    op.create_check_constraint(
        "ck_proposal_status",
        "date_proposals",
        "status IN ('pending', 'accepted', 'refused', 'counter_proposed', 'expired', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_proposal_round_range",
        "date_proposals",
        "round_number >= 1 AND round_number <= 3",
    )
    op.create_check_constraint(
        "ck_proposal_responded_by",
        "date_proposals",
        "responded_by IN ('buyer', 'mechanic') OR responded_by IS NULL",
    )

    # Composite indexes
    op.create_index("ix_proposal_buyer_status", "date_proposals", ["buyer_id", "status"])
    op.create_index("ix_proposal_mechanic_status", "date_proposals", ["mechanic_id", "status"])
    op.create_index("ix_proposal_expires_at", "date_proposals", ["status", "expires_at"])

    # Update notification type check constraint to include proposal types
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "type IN ("
        "'booking_created', 'booking_confirmed', 'booking_refused', "
        "'booking_cancelled', 'check_out_done', 'booking_disputed', "
        "'new_message', 'reminder', 'no_show', 'profile_verification', "
        "'proposal_received', 'proposal_accepted', 'proposal_refused', 'proposal_counter'"
        ")",
    )


def downgrade() -> None:
    # Restore original notification constraint
    op.drop_constraint("ck_notification_type", "notifications", type_="check")
    op.create_check_constraint(
        "ck_notification_type",
        "notifications",
        "type IN ("
        "'booking_created', 'booking_confirmed', 'booking_refused', "
        "'booking_cancelled', 'check_out_done', 'booking_disputed', "
        "'new_message', 'reminder', 'no_show', 'profile_verification'"
        ")",
    )

    op.drop_index("ix_proposal_expires_at", table_name="date_proposals")
    op.drop_index("ix_proposal_mechanic_status", table_name="date_proposals")
    op.drop_index("ix_proposal_buyer_status", table_name="date_proposals")
    op.drop_table("date_proposals")
