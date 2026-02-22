import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID


class MechanicProfile(Base):
    __tablename__ = "mechanic_profiles"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="RESTRICT"), unique=True, nullable=False
    )
    city: Mapped[str] = mapped_column(String(100), nullable=False)
    city_lat: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True, default=None)
    city_lng: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True, default=None)
    max_radius_km: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    free_zone_km: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    # DB-008: accepted_vehicle_types is queried via cast(String).contains() which
    # cannot leverage database indexes, resulting in full table scans. At scale,
    # consider one of the following alternatives:
    #   1. A separate junction table (mechanic_vehicle_types) with a composite index
    #      for normalized many-to-many lookups.
    #   2. A PostgreSQL GIN index on the JSON column:
    #      CREATE INDEX ix_mechanic_vehicle_types_gin
    #        ON mechanic_profiles USING GIN (accepted_vehicle_types);
    #      and querying with the @> (contains) operator instead of cast().contains().
    accepted_vehicle_types: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    # I-005: Numeric(4,2) allows rating_avg up to 99.99 (Numeric(3,2) capped at 9.99
    # which would overflow if a calculation bug produced a value >= 10).
    rating_avg: Mapped[float] = mapped_column(Numeric(4, 2), default=0.0)
    total_reviews: Mapped[int] = mapped_column(Integer, default=0)
    identity_document_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    selfie_with_id_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    cv_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    photo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_identity_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    has_cv: Mapped[bool] = mapped_column(Boolean, default=False)
    has_obd_diagnostic: Mapped[bool] = mapped_column(Boolean, default=False)
    stripe_account_id: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    no_show_count: Mapped[int] = mapped_column(Integer, default=0)
    last_no_show_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    suspended_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    service_location: Mapped[str] = mapped_column(String(20), nullable=False, default="mobile", server_default="mobile")
    garage_address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    referred_by: Mapped[str | None] = mapped_column(String(20), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship("User", back_populates="mechanic_profile", lazy="raise")
    availabilities: Mapped[list["Availability"]] = relationship(
        "Availability", back_populates="mechanic", lazy="raise"
    )
    diplomas: Mapped[list["Diploma"]] = relationship(
        "Diploma", backref="mechanic", lazy="raise"
    )
