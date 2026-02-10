from fastapi import HTTPException, status

from app.models.enums import BookingStatus

# Defines all valid status transitions for a booking
ALLOWED_TRANSITIONS: dict[BookingStatus, set[BookingStatus]] = {
    BookingStatus.PENDING_ACCEPTANCE: {
        BookingStatus.CONFIRMED,
        BookingStatus.CANCELLED,
    },
    BookingStatus.CONFIRMED: {
        BookingStatus.AWAITING_MECHANIC_CODE,
        BookingStatus.CANCELLED,
        BookingStatus.DISPUTED,
    },
    BookingStatus.AWAITING_MECHANIC_CODE: {
        BookingStatus.CHECK_IN_DONE,
    },
    BookingStatus.CHECK_IN_DONE: {
        BookingStatus.CHECK_OUT_DONE,
    },
    BookingStatus.CHECK_OUT_DONE: {
        BookingStatus.VALIDATED,
        BookingStatus.DISPUTED,
    },
    BookingStatus.VALIDATED: {
        BookingStatus.COMPLETED,
    },
    BookingStatus.COMPLETED: set(),  # Terminal state
    BookingStatus.CANCELLED: set(),  # Terminal state
    BookingStatus.DISPUTED: {
        BookingStatus.CANCELLED,   # Resolved in favor of buyer
        BookingStatus.COMPLETED,   # Resolved in favor of mechanic
    },
}


def validate_transition(current: BookingStatus, new: BookingStatus) -> None:
    """Validate a booking status transition. Raises HTTP 409 if invalid."""
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new not in allowed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot transition from '{current.value}' to '{new.value}'",
        )
