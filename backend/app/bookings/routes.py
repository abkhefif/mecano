import json
import uuid
from datetime import datetime, time, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_buyer, get_current_mechanic, get_current_user, get_verified_buyer
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import BookingStatus, DisputeReason, DisputeStatus, UploadedBy, UserRole
from app.models.inspection import InspectionChecklist
from app.models.mechanic_profile import MechanicProfile
from app.models.report import Report
from app.models.user import User
from app.models.validation_proof import ValidationProof
from app.reports.generator import generate_pdf
from app.schemas.booking import (
    BookingBuyerResponse,
    BookingCreateRequest,
    BookingCreateResponse,
    BookingMechanicResponse,
    BookingResponse,
    CheckInRequest,
    CheckInResponse,
    ChecklistInput,
    CheckOutResponse,
    EnterCodeRequest,
    RefuseRequest,
    ValidateRequest,
)
from app.services.pricing import calculate_booking_pricing
from app.services.scheduler import schedule_payment_release
from app.services.storage import upload_file
from app.services.stripe_service import cancel_payment_intent, create_payment_intent
from app.utils.code_generator import generate_check_in_code
from app.utils.geo import calculate_distance_km
from app.utils.booking_state import validate_transition
from app.utils.rate_limit import CODE_ENTRY_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()

MAX_CODE_ATTEMPTS = 5


def _serialize_booking(booking: "Booking", role: UserRole) -> dict:
    """Serialize a booking using the appropriate schema for the user's role."""
    if role == UserRole.BUYER:
        return BookingBuyerResponse.model_validate(booking).model_dump(mode="json")
    elif role == UserRole.MECHANIC:
        return BookingMechanicResponse.model_validate(booking).model_dump(mode="json")
    return BookingResponse.model_validate(booking).model_dump(mode="json")


@router.post("", response_model=BookingCreateResponse, status_code=status.HTTP_201_CREATED)
async def create_booking(
    body: BookingCreateRequest,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new booking (buyer only). Initiates Stripe payment hold."""
    # Fetch availability with row-level lock to prevent double-booking
    avail_result = await db.execute(
        select(Availability)
        .where(Availability.id == body.availability_id)
        .with_for_update()
    )
    availability = avail_result.scalar_one_or_none()
    if not availability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability slot not found")

    if availability.is_booked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This slot is already booked")

    # Check booking is >2h in the future
    slot_datetime = datetime.combine(availability.date, availability.start_time, tzinfo=timezone.utc)
    if slot_datetime - datetime.now(timezone.utc) < timedelta(hours=2):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Booking must be at least 2 hours in advance",
        )

    # Fetch mechanic profile
    mech_result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.id == body.mechanic_id)
    )
    mechanic = mech_result.scalar_one_or_none()
    if not mechanic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic not found")

    if not mechanic.is_identity_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic not verified")

    if availability.mechanic_id != mechanic.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slot does not belong to this mechanic")

    if body.vehicle_type.value not in mechanic.accepted_vehicle_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mechanic does not accept this vehicle type",
        )

    # Calculate distance and pricing
    distance_km = calculate_distance_km(
        mechanic.city_lat, mechanic.city_lng, body.meeting_lat, body.meeting_lng
    )

    if distance_km > mechanic.max_radius_km:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Meeting point is {distance_km:.1f} km away, beyond mechanic's max radius of {mechanic.max_radius_km} km",
        )

    pricing = calculate_booking_pricing(distance_km, mechanic.free_zone_km)

    # Create Stripe PaymentIntent
    amount_cents = int(pricing["total_price"] * 100)
    commission_cents = int(pricing["commission_amount"] * 100)

    intent = await create_payment_intent(
        amount_cents=amount_cents,
        mechanic_stripe_account_id=mechanic.stripe_account_id,
        commission_cents=commission_cents,
        metadata={"buyer_id": str(buyer.id), "mechanic_id": str(mechanic.id)},
    )

    # Create booking -- with compensating Stripe cancellation on DB failure
    try:
        booking = Booking(
            buyer_id=buyer.id,
            mechanic_id=mechanic.id,
            availability_id=availability.id,
            status=BookingStatus.PENDING_ACCEPTANCE,
            vehicle_type=body.vehicle_type,
            vehicle_brand=body.vehicle_brand,
            vehicle_model=body.vehicle_model,
            vehicle_year=body.vehicle_year,
            vehicle_plate=body.vehicle_plate,
            meeting_address=body.meeting_address,
            meeting_lat=body.meeting_lat,
            meeting_lng=body.meeting_lng,
            distance_km=round(distance_km, 2),
            stripe_payment_intent_id=intent["id"],
            **pricing,
        )
        db.add(booking)

        availability.is_booked = True

        # Buffer: block adjacent slots within ±15 min of the booked slot
        # to account for travel/arrival/departure time
        buffer_minutes = 15
        slot_start_dt = datetime.combine(availability.date, availability.start_time)
        slot_end_dt = datetime.combine(availability.date, availability.end_time)
        buffer_start = (slot_start_dt - timedelta(minutes=buffer_minutes)).time()
        buffer_end = (slot_end_dt + timedelta(minutes=buffer_minutes)).time()

        # Find overlapping unbooked slots within the buffer zone on the same day
        from sqlalchemy import and_
        buffer_result = await db.execute(
            select(Availability).where(
                Availability.mechanic_id == availability.mechanic_id,
                Availability.date == availability.date,
                Availability.id != availability.id,
                Availability.is_booked == False,
                # Slot overlaps with buffer zone: slot.start < buffer_end AND slot.end > buffer_start
                Availability.start_time < buffer_end,
                Availability.end_time > buffer_start,
            ).with_for_update()
        )
        for adjacent_slot in buffer_result.scalars().all():
            adjacent_slot.is_booked = True
            logger.info("buffer_slot_blocked", slot_id=str(adjacent_slot.id),
                        reason=f"within 15min buffer of {availability.id}")

        await db.flush()
    except Exception:
        # Compensating transaction: cancel the Stripe intent on DB failure
        await cancel_payment_intent(intent["id"])
        raise

    logger.info("booking_created", booking_id=str(booking.id))

    return BookingCreateResponse(
        booking=BookingResponse.model_validate(booking),
        client_secret=intent["client_secret"],
    )


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
async def accept_booking(
    booking_id: uuid.UUID,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Accept a pending booking (mechanic only)."""
    _, profile = mechanic
    booking = await _get_booking(db, booking_id)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CONFIRMED)

    booking.status = BookingStatus.CONFIRMED
    booking.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    # TODO: Notify buyer
    logger.info("booking_accepted", booking_id=str(booking.id))
    return BookingResponse.model_validate(booking)


@router.patch("/{booking_id}/refuse", response_model=dict)
async def refuse_booking(
    booking_id: uuid.UUID,
    body: RefuseRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Refuse a pending booking (mechanic only). Triggers full refund."""
    _, profile = mechanic
    booking = await _get_booking(db, booking_id)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    # Refuse is only valid for pending bookings (use cancel for confirmed ones)
    if booking.status != BookingStatus.PENDING_ACCEPTANCE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot refuse a booking in '{booking.status.value}' status",
        )

    if booking.stripe_payment_intent_id:
        await cancel_payment_intent(booking.stripe_payment_intent_id)

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)

    if booking.availability:
        booking.availability.is_booked = False

    await db.flush()

    # TODO: Notify buyer
    logger.info("booking_refused", booking_id=str(booking.id), reason=body.reason.value)
    return {"status": "cancelled", "reason": body.reason.value}


@router.patch("/{booking_id}/cancel", response_model=dict)
async def cancel_booking(
    booking_id: uuid.UUID,
    buyer: User = Depends(get_current_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a booking (buyer only). Allowed before check-in."""
    booking = await _get_booking(db, booking_id)

    if booking.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CANCELLED)

    if booking.stripe_payment_intent_id:
        await cancel_payment_intent(booking.stripe_payment_intent_id)

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)

    if booking.availability:
        booking.availability.is_booked = False

    await db.flush()

    logger.info("booking_cancelled_by_buyer", booking_id=str(booking.id))
    return {"status": "cancelled"}


@router.patch("/{booking_id}/check-in", response_model=CheckInResponse)
async def check_in(
    booking_id: uuid.UUID,
    body: CheckInRequest,
    buyer: User = Depends(get_current_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer confirms mechanic presence and generates a 4-digit code."""
    booking = await _get_booking(db, booking_id)

    if booking.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.AWAITING_MECHANIC_CODE)

    # Check time window (30 min tolerance around appointment)
    if not booking.availability:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Availability data missing for this booking",
        )

    slot_dt = datetime.combine(
        booking.availability.date, booking.availability.start_time, tzinfo=timezone.utc
    )
    diff = abs((datetime.now(timezone.utc) - slot_dt).total_seconds())
    if diff > 30 * 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Check-in only allowed within 30 minutes of the appointment time",
        )

    if body.mechanic_present:
        code = generate_check_in_code()
        booking.check_in_code = code
        booking.check_in_code_attempts = 0
        booking.check_in_code_generated_at = datetime.now(timezone.utc)
        booking.status = BookingStatus.AWAITING_MECHANIC_CODE
        await db.flush()

        logger.info("check_in_code_generated", booking_id=str(booking.id))
        return CheckInResponse(check_in_code=code)
    else:
        dispute = DisputeCase(
            booking_id=booking.id,
            opened_by=buyer.id,
            reason=DisputeReason.NO_SHOW,
            description="Mechanic did not show up at the meeting point",
            status=DisputeStatus.OPEN,
        )
        db.add(dispute)
        booking.status = BookingStatus.DISPUTED
        await db.flush()

        # TODO: Notify admin + mechanic
        logger.warning("mechanic_no_show_reported", booking_id=str(booking.id))
        return CheckInResponse(dispute_opened=True)


@router.patch("/{booking_id}/enter-code", response_model=dict)
@limiter.limit(CODE_ENTRY_RATE_LIMIT)
async def enter_code(
    request: Request,
    booking_id: uuid.UUID,
    body: EnterCodeRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Mechanic enters the 4-digit code to confirm physical presence."""
    _, profile = mechanic
    booking = await _get_booking(db, booking_id)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CHECK_IN_DONE)

    # Code expiry check (15 minutes)
    if booking.check_in_code_generated_at:
        elapsed = (datetime.now(timezone.utc) - booking.check_in_code_generated_at).total_seconds()
        if elapsed > 15 * 60:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Code has expired. Please ask the buyer to generate a new code.",
            )

    # Brute-force protection
    if booking.check_in_code_attempts >= MAX_CODE_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please ask the buyer to generate a new code.",
        )

    if booking.check_in_code != body.code:
        booking.check_in_code_attempts += 1
        await db.flush()
        remaining = MAX_CODE_ATTEMPTS - booking.check_in_code_attempts
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incorrect code. {remaining} attempts remaining.",
        )

    booking.status = BookingStatus.CHECK_IN_DONE
    booking.check_in_at = datetime.now(timezone.utc)
    await db.flush()

    logger.info("check_in_confirmed", booking_id=str(booking.id))
    return {"status": "checked_in"}


@router.patch("/{booking_id}/check-out", response_model=CheckOutResponse)
async def check_out(
    booking_id: uuid.UUID,
    photo_plate: UploadFile,
    photo_odometer: UploadFile,
    entered_plate: str,
    entered_odometer_km: int,
    checklist_json: str,
    gps_lat: float | None = None,
    gps_lng: float | None = None,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Mechanic submits inspection results, photos, and checklist. Generates PDF report."""
    user, profile = mechanic
    booking = await _get_booking(db, booking_id)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CHECK_OUT_DONE)

    # Validate form params (since we can't use Pydantic schema with multipart)
    if len(entered_plate) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plate number must be 20 characters or less",
        )
    if entered_odometer_km < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Odometer reading must be non-negative",
        )
    if gps_lat is not None and not (-90 <= gps_lat <= 90):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GPS latitude must be between -90 and 90",
        )
    if gps_lng is not None and not (-180 <= gps_lng <= 180):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="GPS longitude must be between -180 and 180",
        )

    # Parse checklist JSON
    try:
        checklist_data = ChecklistInput.model_validate(json.loads(checklist_json))
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid JSON: {e}")
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid checklist data: {e}")

    # Upload photos
    try:
        plate_url = await upload_file(photo_plate, "proofs")
        odometer_url = await upload_file(photo_odometer, "proofs")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Check if validation proof already exists (idempotency)
    existing_proof_result = await db.execute(
        select(ValidationProof).where(ValidationProof.booking_id == booking.id)
    )
    existing_proof = existing_proof_result.scalar_one_or_none()

    if existing_proof:
        proof = existing_proof
    else:
        # Create validation proof
        proof = ValidationProof(
            booking_id=booking.id,
            photo_plate_url=plate_url,
            photo_odometer_url=odometer_url,
            entered_plate=entered_plate,
            entered_odometer_km=entered_odometer_km,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            uploaded_by=UploadedBy.MECHANIC,
        )
        db.add(proof)

    # Create inspection checklist
    inspection = InspectionChecklist(
        booking_id=booking.id,
        **checklist_data.model_dump(),
    )
    db.add(inspection)
    await db.flush()

    # Generate PDF report with error handling
    try:
        mechanic_name = _get_display_name(user)
        pdf_url = await generate_pdf(booking, proof, inspection, mechanic_name)

        report = Report(booking_id=booking.id, pdf_url=pdf_url)
        db.add(report)
    except Exception as e:
        logger.error("pdf_generation_failed", booking_id=str(booking.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate PDF report. Please try again or contact support."
        )

    booking.status = BookingStatus.CHECK_OUT_DONE
    booking.check_out_at = datetime.now(timezone.utc)
    await db.flush()

    # TODO: Notify buyer
    logger.info("check_out_completed", booking_id=str(booking.id), pdf_url=pdf_url)
    return CheckOutResponse(pdf_url=pdf_url)


@router.patch("/{booking_id}/validate", response_model=dict)
async def validate_booking(
    booking_id: uuid.UUID,
    body: ValidateRequest,
    buyer: User = Depends(get_current_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer validates the inspection results, triggering payment release."""
    booking = await _get_booking(db, booking_id)

    if booking.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.VALIDATED if body.validated else BookingStatus.DISPUTED)

    if body.validated:
        booking.status = BookingStatus.VALIDATED
        await db.flush()

        schedule_payment_release(str(booking.id))

        logger.info("booking_validated", booking_id=str(booking.id))
        return {"status": "validated", "payment_release": "scheduled in 2 hours"}
    else:
        dispute = DisputeCase(
            booking_id=booking.id,
            opened_by=buyer.id,
            reason=body.problem_reason,
            description=body.problem_description,
            status=DisputeStatus.OPEN,
        )
        db.add(dispute)
        booking.status = BookingStatus.DISPUTED
        await db.flush()

        # TODO: Notify admin
        logger.warning("booking_disputed", booking_id=str(booking.id), reason=body.problem_reason.value)
        return {"status": "disputed", "dispute_opened": True}


@router.get("/me")
async def list_my_bookings(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List all bookings for the current user (buyer, mechanic, or admin)."""
    if user.role == UserRole.BUYER:
        result = await db.execute(
            select(Booking)
            .where(Booking.buyer_id == user.id)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic),
                selectinload(Booking.availability)
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    elif user.role == UserRole.ADMIN:
        # Admin sees all bookings
        result = await db.execute(
            select(Booking)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic),
                selectinload(Booking.availability)
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    else:
        # Mechanic
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            return []

        result = await db.execute(
            select(Booking)
            .where(Booking.mechanic_id == profile.id)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic),
                selectinload(Booking.availability)
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .offset(offset)
        )

    return [_serialize_booking(b, user.role) for b in result.scalars().all()]


@router.get("/{booking_id}")
async def get_booking(
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single booking by ID. Users can only access their own bookings."""
    booking = await _get_booking(db, booking_id)

    # Authorization: buyer sees their bookings, mechanic sees theirs, admin sees all
    if user.role == UserRole.ADMIN:
        pass
    elif user.role == UserRole.BUYER:
        if booking.buyer_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")
    else:
        # Mechanic
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile or booking.mechanic_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    return _serialize_booking(booking, user.role)


def _get_display_name(user: User) -> str:
    """Get a display name for a user, preferring first/last name over email."""
    if user.first_name and user.last_name:
        return f"{user.first_name} {user.last_name}"
    if user.first_name:
        return user.first_name
    return user.email.split("@")[0]


async def _get_booking(db: AsyncSession, booking_id: uuid.UUID) -> Booking:
    """Fetch a booking by ID or raise 404. Eagerly loads relationships used by route handlers."""
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.availability),
            selectinload(Booking.mechanic),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking
