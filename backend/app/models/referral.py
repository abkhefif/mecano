import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Integer, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database import Base
from app.models.types import GUID


class ReferralCode(Base):
    __tablename__ = "referral_codes"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    code: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    mechanic_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("mechanic_profiles.id", ondelete="CASCADE"), nullable=False, unique=True)
    uses_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    mechanic = relationship("MechanicProfile", lazy="raise")
