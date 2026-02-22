import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from starlette.requests import Request
# C-002: jwt is imported directly here (rather than via auth/service.py) because
# download tokens are a distinct token type with different claims (booking_id,
# type="download") and short TTL (5 min). Keeping the helper functions
# (_create_download_token, _verify_download_token) co-located with their
# only consumer simplifies maintenance.
import jwt
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.utils.rate_limit import limiter
from app.models.blacklisted_token import BlacklistedToken
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.reports.generator import generate_payment_receipt

logger = structlog.get_logger()
router = APIRouter(prefix="/reports", tags=["reports"])


PAYMENT_STATUS_MAP = {
    BookingStatus.COMPLETED: ("Paye", "status-paid"),
    BookingStatus.VALIDATED: ("En cours de traitement", "status-pending"),
    BookingStatus.CANCELLED: ("Annule", "status-cancelled"),
    BookingStatus.DISPUTED: ("En litige", "status-pending"),
}


def _create_download_token(booking_id: str, user_id: str) -> str:
    """C-04: Create a short-lived (5 min) single-use download token."""
    now = datetime.now(timezone.utc)
    expire = now + timedelta(minutes=5)
    payload = {
        "sub": user_id,
        "booking_id": booking_id,
        "exp": expire,
        "iat": now,
        "iss": "emecano",
        "type": "download",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _verify_download_token(token: str, booking_id: str) -> dict | None:
    """Verify a download token and return the payload dict, or None if invalid."""
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
            issuer="emecano",
            options={"verify_iss": True},
        )
        if payload.get("type") != "download":
            return None
        if payload.get("booking_id") != booking_id:
            return None
        return payload
    except jwt.PyJWTError:
        return None


async def _build_receipt_data(booking: Booking) -> dict:
    """Build receipt template data from a booking."""
    mechanic_city = "Non renseigne"
    if booking.mechanic:
        mechanic_city = booking.mechanic.city

    obd_supplement = None
    if booking.obd_requested:
        obd_supplement = str(
            (booking.total_price - booking.base_price - booking.travel_fees)
            .quantize(Decimal("0.01"))
        )

    status_label, status_class = PAYMENT_STATUS_MAP.get(
        booking.status, ("En attente", "status-pending")
    )

    service_dt = booking.check_in_at or booking.created_at
    service_date = service_dt.strftime("%d/%m/%Y") if service_dt else datetime.now(timezone.utc).strftime("%d/%m/%Y")

    return {
        "receipt_number": str(booking.id)[:8].upper(),
        "service_date": service_date,
        "mechanic_city": mechanic_city,
        "vehicle_brand": booking.vehicle_brand,
        "vehicle_model": booking.vehicle_model,
        "vehicle_year": booking.vehicle_year,
        "base_price": str(booking.base_price.quantize(Decimal("0.01"))),
        "obd_supplement": obd_supplement,
        "travel_fees": str(booking.travel_fees.quantize(Decimal("0.01"))),
        "total_price": str(booking.total_price.quantize(Decimal("0.01"))),
        "payment_status_label": status_label,
        "payment_status_class": status_class,
    }


@router.get("/receipt/{booking_id}")
@limiter.limit("10/minute")
async def get_receipt(
    request: Request,
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate and return a payment receipt PDF for a completed booking."""
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(selectinload(Booking.mechanic))
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # Only the buyer of this booking or an admin can download the receipt
    if user.role != UserRole.ADMIN and booking.buyer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this receipt",
        )

    booking_data = await _build_receipt_data(booking)
    pdf_bytes = await generate_payment_receipt(booking_data)

    logger.info("receipt_generated", booking_id=str(booking.id), user_id=str(user.id))

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="receipt-EM-{booking_data["receipt_number"]}.pdf"',
        },
    )


@router.get("/receipt/{booking_id}/token")
@limiter.limit("10/minute")
async def get_receipt_download_token(
    request: Request,
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """C-04: Generate a short-lived (5 min) download token for a receipt PDF."""
    result = await db.execute(
        select(Booking).where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    if user.role != UserRole.ADMIN and booking.buyer_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this receipt",
        )

    # BUG-010: For admin tokens, encode the buyer_id so download_receipt_with_token
    # can verify against booking.buyer_id (admin's own user_id would fail that check).
    token_user_id = str(booking.buyer_id) if user.role == UserRole.ADMIN else str(user.id)
    token = _create_download_token(str(booking_id), token_user_id)
    logger.info("receipt_download_token_generated", booking_id=str(booking.id), user_id=str(user.id))
    return {"download_token": token, "expires_in_seconds": 300}


@router.get("/receipt/{booking_id}/download")
@limiter.limit("10/minute")
async def download_receipt_with_token(
    request: Request,
    booking_id: uuid.UUID,
    token: str = Query(..., description="Short-lived download token"),
    db: AsyncSession = Depends(get_db),
):
    """C-04: Download a receipt PDF using a short-lived download token (no auth header needed)."""
    token_payload = _verify_download_token(token, str(booking_id))
    if not token_payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired download token",
        )

    user_id = token_payload.get("sub")
    jti = token_payload.get("jti")

    # SEC-009: Check if the token has already been used (single-use enforcement)
    if jti:
        existing = await db.execute(
            select(BlacklistedToken).where(BlacklistedToken.jti == jti)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Download token has already been used",
            )

    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(selectinload(Booking.mechanic))
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Booking not found",
        )

    # Verify the token's user_id matches the booking owner
    if str(booking.buyer_id) != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not authorized to access this receipt",
        )

    booking_data = await _build_receipt_data(booking)
    pdf_bytes = await generate_payment_receipt(booking_data)

    # SEC-009: Blacklist the token JTI to enforce single-use
    # BUG-013: Catch IntegrityError for concurrent requests with the same token
    if jti:
        exp = token_payload.get("exp")
        expires_at = (
            datetime.fromtimestamp(exp, tz=timezone.utc)
            if exp
            else datetime.now(timezone.utc)
        )
        try:
            db.add(BlacklistedToken(jti=jti, expires_at=expires_at))
            await db.flush()
        except IntegrityError:
            await db.rollback()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Download token has already been used",
            )

    logger.info("receipt_downloaded_via_token", booking_id=str(booking.id), user_id=user_id)

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="receipt-EM-{booking_data["receipt_number"]}.pdf"',
        },
    )
