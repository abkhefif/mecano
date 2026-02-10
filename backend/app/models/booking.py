import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Float, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import BookingStatus, VehicleType
from app.models.types import GUID


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id"), nullable=False, index=True
    )
    mechanic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("mechanic_profiles.id"), nullable=False, index=True
    )
    availability_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("availabilities.id"), nullable=True, index=True
    )
    status: Mapped[BookingStatus] = mapped_column(String(30), nullable=False, default=BookingStatus.PENDING_ACCEPTANCE, index=True)
    vehicle_type: Mapped[VehicleType] = mapped_column(String(20), nullable=False)
    vehicle_brand: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_model: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_year: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    meeting_address: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_lat: Mapped[float] = mapped_column(Float, nullable=False)
    meeting_lng: Mapped[float] = mapped_column(Float, nullable=False)
    distance_km: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
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

    buyer: Mapped["User"] = relationship("User", foreign_keys=[buyer_id], lazy="raise")
    mechanic: Mapped["MechanicProfile"] = relationship("MechanicProfile", lazy="raise")
    availability: Mapped["Availability | None"] = relationship("Availability", lazy="raise")
    validation_proof: Mapped["ValidationProof | None"] = relationship(
        "ValidationProof", back_populates="booking", uselist=False, lazy="select"
    )
    inspection_checklist: Mapped["InspectionChecklist | None"] = relationship(
        "InspectionChecklist", back_populates="booking", uselist=False, lazy="select"
    )
    report: Mapped["Report | None"] = relationship(
        "Report", back_populates="booking", uselist=False, lazy="select"
    )
    dispute: Mapped["DisputeCase | None"] = relationship(
        "DisputeCase", back_populates="booking", uselist=False, lazy="select"
    )
    reviews: Mapped[list["Review"]] = relationship(
        "Review", back_populates="booking", lazy="select"
    )
