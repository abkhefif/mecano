import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Index, JSON, Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.types import GUID


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint(
            "type IN ("
            "'booking_created', 'booking_confirmed', 'booking_refused', "
            "'booking_cancelled', 'check_out_done', 'booking_disputed', "
            "'new_message', 'reminder', 'no_show', 'profile_verification'"
            ")",
            name="ck_notification_type",
        ),
        Index("ix_notification_user_created", "user_id", "created_at"),
        Index("ix_notification_user_is_read", "user_id", "is_read"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    user: Mapped["User"] = relationship("User", lazy="raise")
