import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import ProposalStatus, VehicleType
from app.models.types import GUID


class DateProposal(Base):
    __tablename__ = "date_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'accepted', 'refused', 'counter_proposed', 'expired', 'cancelled')",
            name="ck_proposal_status",
        ),
        CheckConstraint(
            "round_number >= 1 AND round_number <= 3",
            name="ck_proposal_round_range",
        ),
        CheckConstraint(
            "responded_by IN ('buyer', 'mechanic') OR responded_by IS NULL",
            name="ck_proposal_responded_by",
        ),
        Index("ix_proposal_buyer_status", "buyer_id", "status"),
        Index("ix_proposal_mechanic_status", "mechanic_id", "status"),
        Index("ix_proposal_expires_at", "status", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    mechanic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("mechanic_profiles.id", ondelete="CASCADE"), nullable=False, index=True
    )
    proposed_date: Mapped[date] = mapped_column(Date, nullable=False)
    proposed_time: Mapped[str] = mapped_column(String(5), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[ProposalStatus] = mapped_column(
        String(30), nullable=False, default=ProposalStatus.PENDING
    )
    round_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("date_proposals.id", ondelete="SET NULL"), nullable=True
    )
    responded_by: Mapped[str | None] = mapped_column(String(10), nullable=True)
    booking_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True
    )

    # Vehicle info (carried through the negotiation chain)
    vehicle_type: Mapped[VehicleType] = mapped_column(String(20), nullable=False)
    vehicle_brand: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_model: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_year: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)
    meeting_address: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    meeting_lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    obd_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    buyer: Mapped["User"] = relationship("User", foreign_keys=[buyer_id], lazy="raise")
    mechanic: Mapped["MechanicProfile"] = relationship("MechanicProfile", lazy="raise")
    parent: Mapped["DateProposal | None"] = relationship(
        "DateProposal", remote_side=[id], lazy="raise"
    )
    booking: Mapped["Booking | None"] = relationship("Booking", lazy="raise")
