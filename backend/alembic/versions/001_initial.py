"""Initial schema

Revision ID: 001
Revises:
Create Date: 2025-01-01 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Users
    op.create_table(
        "users",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False, index=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("first_name", sa.String(100), nullable=True),
        sa.Column("last_name", sa.String(100), nullable=True),
        sa.Column("is_verified", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Mechanic Profiles
    op.create_table(
        "mechanic_profiles",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), unique=True, nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("city_lat", sa.Float(), nullable=False, default=0.0),
        sa.Column("city_lng", sa.Float(), nullable=False, default=0.0),
        sa.Column("max_radius_km", sa.Integer(), nullable=False, default=30),
        sa.Column("free_zone_km", sa.Integer(), nullable=False, default=10),
        sa.Column("accepted_vehicle_types", sa.JSON(), nullable=False),
        sa.Column("rating_avg", sa.Float(), default=0.0),
        sa.Column("total_reviews", sa.Integer(), default=0),
        sa.Column("identity_document_url", sa.String(500), nullable=True),
        sa.Column("selfie_with_id_url", sa.String(500), nullable=True),
        sa.Column("cv_url", sa.String(500), nullable=True),
        sa.Column("is_identity_verified", sa.Boolean(), default=False),
        sa.Column("has_cv", sa.Boolean(), default=False),
        sa.Column("stripe_account_id", sa.String(255), nullable=True),
        sa.Column("no_show_count", sa.Integer(), default=0),
        sa.Column("last_no_show_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("suspended_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Availabilities
    op.create_table(
        "availabilities",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("mechanic_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("mechanic_profiles.id"), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("start_time", sa.Time(), nullable=False),
        sa.Column("end_time", sa.Time(), nullable=False),
        sa.Column("is_booked", sa.Boolean(), default=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_availabilities_mechanic_date", "availabilities", ["mechanic_id", "date"])

    # Bookings
    op.create_table(
        "bookings",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("buyer_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("mechanic_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("mechanic_profiles.id"), nullable=False),
        sa.Column("availability_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("availabilities.id"), nullable=True),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("vehicle_type", sa.String(20), nullable=False),
        sa.Column("vehicle_brand", sa.String(100), nullable=False),
        sa.Column("vehicle_model", sa.String(100), nullable=False),
        sa.Column("vehicle_year", sa.Integer(), nullable=False),
        sa.Column("vehicle_plate", sa.String(20), nullable=True),
        sa.Column("meeting_address", sa.Text(), nullable=False),
        sa.Column("meeting_lat", sa.Float(), nullable=False),
        sa.Column("meeting_lng", sa.Float(), nullable=False),
        sa.Column("distance_km", sa.Float(), nullable=False),
        sa.Column("base_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("travel_fees", sa.Numeric(10, 2), nullable=False),
        sa.Column("total_price", sa.Numeric(10, 2), nullable=False),
        sa.Column("commission_rate", sa.Numeric(5, 4), nullable=False),
        sa.Column("commission_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("mechanic_payout", sa.Numeric(10, 2), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(255), nullable=True),
        sa.Column("check_in_code", sa.String(4), nullable=True),
        sa.Column("check_in_code_attempts", sa.Integer(), default=0),
        sa.Column("check_in_code_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_in_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("check_out_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("payment_released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Indexes on bookings
    op.create_index("ix_bookings_buyer_id", "bookings", ["buyer_id"])
    op.create_index("ix_bookings_mechanic_id", "bookings", ["mechanic_id"])
    op.create_index("ix_bookings_status", "bookings", ["status"])
    op.create_index("ix_bookings_availability_id", "bookings", ["availability_id"])
    op.create_index("ix_bookings_stripe_payment_intent_id", "bookings", ["stripe_payment_intent_id"])

    # Validation Proofs
    op.create_table(
        "validation_proofs",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id"), unique=True, nullable=False),
        sa.Column("photo_plate_url", sa.String(500), nullable=False),
        sa.Column("photo_odometer_url", sa.String(500), nullable=False),
        sa.Column("entered_plate", sa.String(20), nullable=False),
        sa.Column("entered_odometer_km", sa.Integer(), nullable=False),
        sa.Column("gps_lat", sa.Float(), nullable=True),
        sa.Column("gps_lng", sa.Float(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("uploaded_by", sa.String(20), nullable=False),
    )

    # Inspection Checklists
    op.create_table(
        "inspection_checklists",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id"), unique=True, nullable=False),
        sa.Column("brakes", sa.String(20), nullable=False),
        sa.Column("tires", sa.String(20), nullable=False),
        sa.Column("fluids", sa.String(20), nullable=False),
        sa.Column("battery", sa.String(20), nullable=False),
        sa.Column("suspension", sa.String(20), nullable=False),
        sa.Column("body", sa.String(20), nullable=False),
        sa.Column("exhaust", sa.String(20), nullable=False),
        sa.Column("lights", sa.String(20), nullable=False),
        sa.Column("test_drive_done", sa.Boolean(), nullable=False),
        sa.Column("test_drive_behavior", sa.String(20), nullable=True),
        sa.Column("remarks", sa.Text(), nullable=True),
        sa.Column("recommendation", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Reports
    op.create_table(
        "reports",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id"), unique=True, nullable=False),
        sa.Column("pdf_url", sa.String(500), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Reviews
    op.create_table(
        "reviews",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id"), nullable=False),
        sa.Column("reviewer_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reviewee_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("is_public", sa.Boolean(), nullable=False, default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("booking_id", "reviewer_id", name="uq_review_booking_reviewer"),
    )
    op.create_index("ix_reviews_reviewee_id", "reviews", ["reviewee_id"])

    # Dispute Cases
    op.create_table(
        "dispute_cases",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("bookings.id"), unique=True, nullable=False),
        sa.Column("opened_by", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("reason", sa.String(20), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_by_admin", sa.dialects.postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("resolution_notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # Processed Webhook Events (idempotency)
    op.create_table(
        "processed_webhook_events",
        sa.Column("event_id", sa.String(255), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("processed_webhook_events")
    op.drop_table("dispute_cases")
    op.drop_index("ix_reviews_reviewee_id", table_name="reviews")
    op.drop_table("reviews")
    op.drop_table("reports")
    op.drop_table("inspection_checklists")
    op.drop_table("validation_proofs")
    op.drop_index("ix_bookings_buyer_id", table_name="bookings")
    op.drop_index("ix_bookings_mechanic_id", table_name="bookings")
    op.drop_index("ix_bookings_status", table_name="bookings")
    op.drop_index("ix_bookings_availability_id", table_name="bookings")
    op.drop_index("ix_bookings_stripe_payment_intent_id", table_name="bookings")
    op.drop_table("bookings")
    op.drop_index("ix_availabilities_mechanic_date", table_name="availabilities")
    op.drop_table("availabilities")
    op.drop_table("mechanic_profiles")
    op.drop_table("users")
