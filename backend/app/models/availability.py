import uuid
from datetime import date, datetime, time

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Index, Time, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID


class Availability(Base):
    __tablename__ = "availabilities"
    __table_args__ = (
        Index("ix_availability_mechanic_date", "mechanic_id", "date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    mechanic_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("mechanic_profiles.id"), nullable=False, index=True
    )
    date: Mapped[date] = mapped_column(Date, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    is_booked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mechanic: Mapped["MechanicProfile"] = relationship(
        "MechanicProfile", back_populates="availabilities", lazy="raise"
    )
