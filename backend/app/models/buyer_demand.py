import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.enums import DemandStatus, VehicleType
from app.models.types import GUID


class BuyerDemand(Base):
    """A reverse-booking demand posted by a buyer seeking a vehicle inspection."""

    __tablename__ = "buyer_demands"
    __table_args__ = (
        Index("ix_buyer_demand_buyer_status", "buyer_id", "status"),
        Index("ix_buyer_demand_status_expires", "status", "expires_at"),
        Index("ix_buyer_demand_desired_date", "desired_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Vehicle information
    vehicle_type: Mapped[VehicleType] = mapped_column(String(20), nullable=False)
    vehicle_brand: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_model: Mapped[str] = mapped_column(String(100), nullable=False)
    vehicle_year: Mapped[int] = mapped_column(Integer, nullable=False)
    vehicle_plate: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Meeting location
    meeting_address: Mapped[str] = mapped_column(Text, nullable=False)
    meeting_lat: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)
    meeting_lng: Mapped[float] = mapped_column(Numeric(9, 6), nullable=False)

    # Time window
    desired_date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)

    obd_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[DemandStatus] = mapped_column(
        String(20), nullable=False, default=DemandStatus.OPEN
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # Relationships
    buyer: Mapped["User"] = relationship("User", foreign_keys=[buyer_id], lazy="raise")
    interests: Mapped[list["DemandInterest"]] = relationship(
        "DemandInterest", back_populates="demand", lazy="raise"
    )


class DemandInterest(Base):
    """A mechanic's expression of interest in a buyer demand."""

    __tablename__ = "demand_interests"
    __table_args__ = (
        UniqueConstraint("demand_id", "mechanic_id", name="uq_demand_mechanic"),
        Index("ix_demand_interest_demand", "demand_id"),
        Index("ix_demand_interest_mechanic", "mechanic_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    demand_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("buyer_demands.id", ondelete="CASCADE"), nullable=False
    )
    mechanic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("mechanic_profiles.id", ondelete="CASCADE"), nullable=False
    )
    proposal_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("date_proposals.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    demand: Mapped["BuyerDemand"] = relationship("BuyerDemand", back_populates="interests", lazy="raise")
    mechanic: Mapped["MechanicProfile"] = relationship("MechanicProfile", lazy="raise")
    proposal: Mapped["DateProposal | None"] = relationship("DateProposal", lazy="raise")
