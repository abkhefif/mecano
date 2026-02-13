import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import BookingStatus, VehicleType
from app.models.types import GUID


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        CheckConstraint("base_price >= 0", name="ck_booking_base_price_positive"),
        CheckConstraint("total_price >= 0", name="ck_booking_total_price_positive"),
        CheckConstraint("commission_rate >= 0 AND commission_rate <= 1", name="ck_booking_commission_rate_range"),
        Index("ix_booking_buyer_created", "buyer_id", "created_at"),
        Index("ix_booking_mechanic_created", "mechanic_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mechanic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("mechanic_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    availability_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("availabilities.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[BookingStatus] = mapped_column(String(30), nullable=False, default=BookingStatus.PENDING_ACCEPTANCE, index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(String(20), nullable=False)
    vehicle_brand: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_model: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_year: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    meeting_address: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    meeting_lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    distance_km: Mapped[float] = mapped_column(Numeric(6, 2), nullable=False, default=0.0)
    obd_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    travel_fees: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0.00"))
    total_price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    commission_rate: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False)
    commission_amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    mechanic_payout: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stripe_payment_intent_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    check_in_code: Mapped[str | None] = mapped_column(String(4), nullable=True)
    check_in_code_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    check_in_code_generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payment_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The following fields are intentionally nullable — they are only populated
    # when a booking is cancelled or refused, so NULL conveys "not applicable".
    # cancelled_by: "buyer" | "mechanic" | NULL (booking still active)
    # refuse_reason: set only when a mechanic refuses (CANCELLED with reason)
    # proposed_time: optional counter-proposal time when mechanic refuses
    # refund_percentage / refund_amount: set only on buyer-initiated cancellations
    refuse_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    proposed_time: Mapped[str | None] = mapped_column(String(5), nullable=True)
    cancelled_by: Mapped[str | None] = mapped_column(String(10), nullable=True)
    refund_percentage: Mapped[int | None] = mapped_column(Integer, nullable=True)
    refund_amount: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    reminder_24h_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reminder_2h_sent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mechanic_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    mechanic_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    mechanic_location_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    buyer: Mapped["User"] = relationship("User", foreign_keys=[buyer_id], lazy="raise")
    mechanic: Mapped["MechanicProfile"] = relationship("MechanicProfile", lazy="raise")
    availability: Mapped["Availability | None"] = relationship("Availability", lazy="raise")
    validation_proof: Mapped["ValidationProof | None"] = relationship(
        "ValidationProof", back_populates="booking", uselist=False, lazy="raise"
    )
    inspection_checklist: Mapped["InspectionChecklist | None"] = relationship(
        "InspectionChecklist", back_populates="booking", uselist=False, lazy="raise"
    )
    report: Mapped["Report | None"] = relationship(
        "Report", back_populates="booking", uselist=False, lazy="raise"
    )
    dispute: Mapped["DisputeCase | None"] = relationship(
        "DisputeCase", back_populates="booking", uselist=False, lazy="raise"
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="booking", lazy="raise"
    )
