import asyncio
import hmac
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, status
from starlette.responses import Response
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_buyer, get_current_mechanic, get_current_user, get_verified_buyer
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import BookingStatus, DisputeReason, DisputeStatus, NotificationType, UploadedBy, UserRole
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
    LocationUpdate,
    RefuseRequest,
    ValidateRequest,
)
from app.services.notifications import create_notification
from app.services.pricing import calculate_booking_pricing
from app.services.scheduler import schedule_payment_release
from app.services.storage import upload_file
from app.services.stripe_service import (
    StripeServiceError,
    cancel_payment_intent,
    capture_payment_intent,
    create_ephemeral_key,
    create_payment_intent,
    get_or_create_customer,
    refund_payment_intent,
)
from app.config import settings
from app.utils.code_generator import generate_check_in_code, hash_check_in_code, verify_check_in_code
from app.utils.display_name import get_display_name
from app.utils.geo import calculate_distance_km
from app.utils.booking_state import validate_transition
from app.utils.rate_limit import CODE_ENTRY_RATE_LIMIT, LIST_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()

MAX_CODE_ATTEMPTS = settings.MAX_CHECK_IN_CODE_ATTEMPTS
# QC-005: Named constant for the no-show GPS proximity threshold
NO_SHOW_DISTANCE_THRESHOLD_KM = 0.5
# QC-006: Named constant for check-in code expiry duration
CHECK_IN_CODE_EXPIRY_SECONDS = 15 * 60


def _serialize_booking(booking: "Booking", role: UserRole) -> dict[str, Any]:
    """Serialize a booking using the appropriate schema for the user's role."""
    if role == UserRole.BUYER:
        data = BookingBuyerResponse.model_validate(booking).model_dump(mode="json")
    elif role == UserRole.MECHANIC:
        data = BookingMechanicResponse.model_validate(booking).model_dump(mode="json")
    else:
        data = BookingResponse.model_validate(booking).model_dump(mode="json")

    # Add slot time info from linked availability
    if booking.availability:
        data["slot_date"] = booking.availability.date.isoformat()
        data["slot_start_time"] = booking.availability.start_time.strftime("%H:%M")
        data["slot_end_time"] = booking.availability.end_time.strftime("%H:%M")

    # Add refuse info
    data["refuse_reason"] = booking.refuse_reason
    data["proposed_time"] = booking.proposed_time

    # Add review presence flag (reviews is eagerly loaded)
    data["has_review"] = len(booking.reviews) > 0 if booking.reviews else False

    # R-002: Mask vehicle_plate for mechanics on terminal bookings
    # (privacy: plate should not remain visible after the service is done)
    if role == UserRole.MECHANIC and booking.status in (
        BookingStatus.COMPLETED, BookingStatus.CANCELLED
    ):
        data["vehicle_plate"] = None

    # Add contact phone when booking is CONFIRMED and close to appointment
    if booking.status == BookingStatus.CONFIRMED and booking.availability:
        slot_dt = datetime.combine(
            booking.availability.date,
            booking.availability.start_time,
            tzinfo=timezone.utc,
        )
        time_until = slot_dt - datetime.now(timezone.utc)
        if time_until <= timedelta(hours=settings.BOOKING_MINIMUM_ADVANCE_HOURS):
            if role == UserRole.BUYER:
                # Buyer sees mechanic's phone
                mechanic_user = booking.mechanic.user if booking.mechanic else None
                data["contact_phone"] = mechanic_user.phone if mechanic_user else None
            elif role == UserRole.MECHANIC:
                # Mechanic sees buyer's phone
                data["contact_phone"] = booking.buyer.phone if booking.buyer else None

    return data


@router.post("", response_model=BookingCreateResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_booking(
    request: Request,
    body: BookingCreateRequest,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Create a new booking (buyer only). Initiates Stripe payment hold."""
    # AUDIT-1: Require phone number before transaction
    if not buyer.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Un numéro de téléphone est requis pour effectuer une réservation. Mettez à jour votre profil.",
        )

    # Fetch availability with row-level lock to prevent double-booking.
    # Use nowait=True to fail immediately instead of blocking indefinitely,
    # which prevents deadlocks when two concurrent requests target the same slot.
    try:
        avail_result = await db.execute(
            select(Availability)
            .where(Availability.id == body.availability_id)
            .with_for_update(nowait=True)
        )
    except OperationalError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This slot is currently being booked by another user. Please try again.",
        )
    availability = avail_result.scalar_one_or_none()
    if not availability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability slot not found")

    if availability.is_booked:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This slot is already booked")

    SLOT_DURATION_MINUTES = settings.BOOKING_SLOT_DURATION_MINUTES

    # Check booking is sufficiently in the future BEFORE any availability split
    # so that a rejected booking doesn't leave orphaned split slots.
    # FIX-8: Robust slot_start_time validation with clear error message
    if body.slot_start_time:
        try:
            _check_start = time.fromisoformat(body.slot_start_time)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid slot_start_time format: '{body.slot_start_time}'. Expected HH:MM (e.g. '09:00')",
            )
    else:
        _check_start = availability.start_time
    _check_datetime = datetime.combine(availability.date, _check_start, tzinfo=timezone.utc)
    if _check_datetime - datetime.now(timezone.utc) < timedelta(hours=settings.BOOKING_MINIMUM_ADVANCE_HOURS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking must be at least {settings.BOOKING_MINIMUM_ADVANCE_HOURS} hours in advance",
        )
    # FIN-04: Stripe authorizations expire after 7 days. Reject bookings too
    # far in the future to prevent capture failures on expired authorizations.
    max_advance = timedelta(days=settings.STRIPE_AUTH_MAX_ADVANCE_DAYS)
    if _check_datetime - datetime.now(timezone.utc) > max_advance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking cannot be more than {settings.STRIPE_AUTH_MAX_ADVANCE_DAYS} days in advance due to payment authorization limits",
        )

    # If buyer chose a sub-slot within a larger availability window, split it
    booked_slot = availability  # by default, book the whole slot
    if body.slot_start_time:
        # FIX-8: already validated above, safe to parse
        chosen_start = time.fromisoformat(body.slot_start_time)
        chosen_end_dt = datetime.combine(availability.date, chosen_start) + timedelta(minutes=SLOT_DURATION_MINUTES)
        chosen_end = chosen_end_dt.time()

        # Validate the chosen sub-slot falls within the availability window
        if chosen_start < availability.start_time or chosen_end > availability.end_time:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chosen time {body.slot_start_time} is outside the availability window {availability.start_time.strftime('%H:%M')}-{availability.end_time.strftime('%H:%M')}",
            )

        # Split: create a new 30-min slot for the booking, shrink/split the original
        # Case 1: exact match — no split needed
        if chosen_start == availability.start_time and chosen_end == availability.end_time:
            pass  # booked_slot = availability, no changes needed
        else:
            # Capture original slot details before deletion
            orig_mechanic_id = availability.mechanic_id
            orig_date = availability.date
            orig_start = availability.start_time
            orig_end = availability.end_time

            # Delete the original big slot first to avoid UNIQUE constraint
            # violations when creating split pieces that share the same
            # (mechanic_id, date, start_time) as the original.
            await db.delete(availability)
            await db.flush()

            # Create the 30-min booked sub-slot
            booked_slot = Availability(
                id=uuid.uuid4(),
                mechanic_id=orig_mechanic_id,
                date=orig_date,
                start_time=chosen_start,
                end_time=chosen_end,
                is_booked=False,  # will be set to True below
            )
            db.add(booked_slot)

            # Adjust the original slot: create remaining pieces
            if chosen_start > orig_start:
                # Left piece: original_start → chosen_start
                left_slot = Availability(
                    id=uuid.uuid4(),
                    mechanic_id=orig_mechanic_id,
                    date=orig_date,
                    start_time=orig_start,
                    end_time=chosen_start,
                    is_booked=False,
                )
                db.add(left_slot)

            if chosen_end < orig_end:
                # Right piece: chosen_end → original_end
                right_slot = Availability(
                    id=uuid.uuid4(),
                    mechanic_id=orig_mechanic_id,
                    date=orig_date,
                    start_time=chosen_end,
                    end_time=orig_end,
                    is_booked=False,
                )
                db.add(right_slot)

            await db.flush()

            logger.info(
                "availability_split",
                original_id=str(availability.id),
                booked_slot_id=str(booked_slot.id),
                chosen_time=body.slot_start_time,
            )

    # Fetch mechanic profile
    mech_result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.id == body.mechanic_id)
    )
    mechanic = mech_result.scalar_one_or_none()
    if not mechanic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic not found")

    # BUG-006: Prevent buyer from booking their own services
    if mechanic.user_id == buyer.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot book your own services")

    # AUDIT-1: Verify mechanic has phone for buyer contact
    mech_user_result = await db.execute(select(User).where(User.id == mechanic.user_id))
    mech_user = mech_user_result.scalar_one_or_none()
    if mech_user and not mech_user.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ce mécanicien doit d'abord renseigner son numéro de téléphone.",
        )

    if not mechanic.is_identity_verified:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic not verified")

    # AUD-006: Verify mechanic is active and not suspended
    if not mechanic.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic is not currently active")
    if mechanic.suspended_until and mechanic.suspended_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic is currently suspended")

    if booked_slot.mechanic_id != mechanic.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Slot does not belong to this mechanic")

    if body.vehicle_type.value not in mechanic.accepted_vehicle_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mechanic does not accept this vehicle type",
        )

    if body.obd_requested and not mechanic.has_obd_diagnostic:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This mechanic does not offer OBD diagnostic service",
        )

    # R-008: Guard against NULL mechanic coordinates
    if mechanic.city_lat is None or mechanic.city_lng is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mechanic has not set their service location",
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

    pricing = calculate_booking_pricing(distance_km, mechanic.free_zone_km, obd_requested=body.obd_requested)

    # Verify mechanic has completed Stripe onboarding
    if not mechanic.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="This mechanic has not completed payment onboarding yet",
        )

    # Create Stripe PaymentIntent
    # PAY-H3: Use ROUND_HALF_UP consistently (not round() which uses ROUND_HALF_EVEN)
    amount_cents = int((pricing["total_price"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    commission_cents = int((pricing["commission_amount"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Create or get Stripe Customer for saved payment methods
    customer_id = await get_or_create_customer(
        email=buyer.email,
        user_id=str(buyer.id),
        existing_customer_id=buyer.stripe_customer_id,
    )
    if not buyer.stripe_customer_id:
        buyer.stripe_customer_id = customer_id

    intent = await create_payment_intent(
        amount_cents=amount_cents,
        mechanic_stripe_account_id=mechanic.stripe_account_id,
        commission_cents=commission_cents,
        metadata={"buyer_id": str(buyer.id), "mechanic_id": str(mechanic.id)},
        # S-01: Include a nonce to prevent key collision if a prior booking for the
        # same slot was cancelled and re-created at the same price
        idempotency_key=f"booking_{buyer.id}_{body.availability_id}_{uuid.uuid4().hex[:8]}",
        customer_id=customer_id,
    )

    # Create booking -- with compensating Stripe cancellation on DB failure
    try:
        booking = Booking(
            buyer_id=buyer.id,
            mechanic_id=mechanic.id,
            availability_id=booked_slot.id,
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
            obd_requested=body.obd_requested,
            stripe_payment_intent_id=intent["id"],
            **pricing,
        )
        db.add(booking)

        booked_slot.is_booked = True

        # Buffer: block adjacent slots within buffer zone of the booked slot
        # to account for travel/arrival/departure time
        buffer_minutes = settings.BOOKING_BUFFER_ZONE_MINUTES
        slot_start_dt = datetime.combine(booked_slot.date, booked_slot.start_time)
        slot_end_dt = datetime.combine(booked_slot.date, booked_slot.end_time)
        buffer_start = (slot_start_dt - timedelta(minutes=buffer_minutes)).time()
        buffer_end = (slot_end_dt + timedelta(minutes=buffer_minutes)).time()

        # Find overlapping unbooked slots within the buffer zone on the same day
        # Trim them instead of marking entirely as booked
        # Use skip_locked=True for buffer slots: if another transaction already
        # holds the lock on an adjacent slot, skip it rather than deadlocking.
        # Skipped slots will be handled by the next booking attempt or cron job.
        buffer_result = await db.execute(
            select(Availability).where(
                Availability.mechanic_id == booked_slot.mechanic_id,
                Availability.date == booked_slot.date,
                Availability.id != booked_slot.id,
                Availability.is_booked == False,
                # Slot overlaps with buffer zone: slot.start < buffer_end AND slot.end > buffer_start
                Availability.start_time < buffer_end,
                Availability.end_time > buffer_start,
            ).with_for_update(skip_locked=True)
        )
        for adjacent_slot in buffer_result.scalars().all():
            # If entirely within buffer → mark as booked
            if adjacent_slot.start_time >= buffer_start and adjacent_slot.end_time <= buffer_end:
                adjacent_slot.is_booked = True
                logger.info("buffer_slot_blocked", slot_id=str(adjacent_slot.id))
            else:
                # Partially overlapping → trim the slot to exclude buffer zone
                new_start = adjacent_slot.start_time
                new_end = adjacent_slot.end_time

                if new_start < buffer_start:
                    # Slot extends before buffer: keep the part before buffer
                    new_end = buffer_start
                elif new_end > buffer_end:
                    # Slot extends after buffer: keep the part after buffer
                    new_start = buffer_end

                # Check if remaining slot is at least 30 min
                remaining = (datetime.combine(booked_slot.date, new_end) - datetime.combine(booked_slot.date, new_start)).total_seconds() / 60
                if remaining < SLOT_DURATION_MINUTES:
                    adjacent_slot.is_booked = True
                    logger.info("buffer_slot_blocked_too_short", slot_id=str(adjacent_slot.id), remaining_min=remaining)
                else:
                    adjacent_slot.start_time = new_start
                    adjacent_slot.end_time = new_end
                    logger.info("buffer_slot_trimmed", slot_id=str(adjacent_slot.id), new_start=str(new_start), new_end=str(new_end))

        await db.flush()
    except Exception as e:
        logger.exception("booking_creation_failed", error=str(e))
        # Compensating transaction: cancel the Stripe intent on DB failure
        try:
            await cancel_payment_intent(intent["id"])
        except Exception as cancel_err:
            logger.exception(
                "booking_creation_cancel_payment_failed",
                intent_id=intent["id"],
                error=str(cancel_err),
            )
        raise

    from app.metrics import BOOKINGS_CREATED
    BOOKINGS_CREATED.labels(status="pending_acceptance").inc()

    logger.info("booking_created", booking_id=str(booking.id))

    # Notify mechanic about the new booking request
    await create_notification(
        db=db,
        user_id=mechanic.user_id,
        notification_type=NotificationType.BOOKING_CREATED,
        title="Nouvelle demande de RDV",
        body=f"Un acheteur souhaite reserver un controle pour {body.vehicle_brand} {body.vehicle_model}.",
        data={"booking_id": str(booking.id)},
    )

    # F-009: Use BookingBuyerResponse to hide commission_amount/mechanic_payout
    # from the buyer who creates the booking.
    # L-003: Set Cache-Control: no-store to prevent caching of client_secret
    ephemeral_key = await create_ephemeral_key(customer_id)

    from fastapi.responses import JSONResponse as _JSONResponse
    response_data = BookingCreateResponse(
        booking=BookingBuyerResponse.model_validate(booking),
        client_secret=intent["client_secret"],
        ephemeral_key=ephemeral_key,
        customer_id=customer_id,
    )
    return _JSONResponse(
        status_code=status.HTTP_201_CREATED,
        content=response_data.model_dump(mode="json"),
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/{booking_id}/accept", response_model=BookingResponse)
@limiter.limit("10/minute")
async def accept_booking(
    request: Request,
    booking_id: uuid.UUID,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Accept a pending booking (mechanic only)."""
    _, profile = mechanic
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CONFIRMED, action="accept")

    # AUD-015: Verify the booking has a payment intent before accepting
    if not booking.stripe_payment_intent_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Booking has no payment associated")

    booking.status = BookingStatus.CONFIRMED
    booking.confirmed_at = datetime.now(timezone.utc)
    await db.flush()

    # Notify buyer that booking is confirmed
    await create_notification(
        db=db,
        user_id=booking.buyer_id,
        notification_type=NotificationType.BOOKING_CONFIRMED,
        title="RDV confirme !",
        body="Le mecanicien a accepte votre demande de rendez-vous.",
        data={"booking_id": str(booking.id)},
    )

    logger.info("booking_accepted", booking_id=str(booking.id))
    return BookingResponse.model_validate(booking)


@router.patch("/{booking_id}/refuse", response_model=dict)
@limiter.limit("10/minute")
async def refuse_booking(
    request: Request,
    booking_id: uuid.UUID,
    body: RefuseRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Refuse a pending booking (mechanic only). Triggers full refund."""
    _, profile = mechanic
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    # Refuse is only valid for pending bookings (use cancel for confirmed ones)
    if booking.status != BookingStatus.PENDING_ACCEPTANCE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot refuse a booking in '{booking.status.value}' status",
        )

    # Mechanic refuses = 100% refund to buyer
    refund_amount = booking.total_price

    if booking.stripe_payment_intent_id:
        try:
            await cancel_payment_intent(booking.stripe_payment_intent_id)
        except StripeServiceError as e:
            logger.error("stripe_refuse_error", error=str(e), booking_id=str(booking.id))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Payment processing failed. Please try again or contact support.",
            )

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.refuse_reason = body.reason.value
    booking.proposed_time = body.proposed_time
    booking.cancelled_by = "mechanic"
    booking.refund_percentage = 100
    booking.refund_amount = refund_amount

    # R-01: Lock availability and only release if no other active booking references it
    if booking.availability_id:
        avail_result = await db.execute(
            select(Availability).where(Availability.id == booking.availability_id).with_for_update()
        )
        avail = avail_result.scalar_one_or_none()
        if avail:
            other_active = await db.execute(
                select(func.count(Booking.id)).where(
                    Booking.availability_id == booking.availability_id,
                    Booking.id != booking.id,
                    Booking.status != BookingStatus.CANCELLED,
                )
            )
            if (other_active.scalar() or 0) == 0:
                avail.is_booked = False

    await db.flush()

    # Notify buyer that booking was refused
    await create_notification(
        db=db,
        user_id=booking.buyer_id,
        notification_type=NotificationType.BOOKING_REFUSED,
        title="RDV refuse",
        body="Le mecanicien a decline votre demande. Vous serez integralement rembourse.",
        data={"booking_id": str(booking.id), "reason": body.reason.value, "proposed_time": body.proposed_time},
    )

    logger.info(
        "booking_refused",
        booking_id=str(booking.id),
        reason=body.reason.value,
        proposed_time=body.proposed_time,
        refund_amount=str(refund_amount),
    )
    return {"status": "cancelled", "reason": body.reason.value, "proposed_time": body.proposed_time}


@router.patch("/{booking_id}/cancel", response_model=dict)
@limiter.limit("10/minute")
async def cancel_booking(
    request: Request,
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a booking (buyer or mechanic). Applies refund policy based on time to appointment.

    F-012: A suspended mechanic is still allowed to cancel their bookings
    (to not leave buyers stranded). The suspension check in get_current_user
    does not apply here because this endpoint uses get_current_user (not
    get_current_mechanic), which does not enforce the suspension guard.
    """
    booking = await _get_booking(db, booking_id, lock=True)

    # Determine who is cancelling
    if user.role == UserRole.BUYER:
        if booking.buyer_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")
        cancelled_by = "buyer"
    elif user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile or booking.mechanic_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")
        cancelled_by = "mechanic"
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admins cannot cancel bookings via this endpoint")

    validate_transition(booking.status, BookingStatus.CANCELLED, action="cancel")

    # Calculate time until appointment
    refund_pct = 100  # default
    if cancelled_by == "buyer" and booking.availability:
        appointment_dt = datetime.combine(
            booking.availability.date, booking.availability.start_time, tzinfo=timezone.utc
        )
        hours_until = (appointment_dt - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_until > settings.CANCELLATION_FULL_REFUND_HOURS:
            refund_pct = 100
        elif hours_until > settings.CANCELLATION_PARTIAL_REFUND_HOURS:
            refund_pct = 50
        else:
            refund_pct = 0
    # Mechanic cancellation: always 100% refund to buyer

    # Calculate refund amount
    refund_amount = (booking.total_price * Decimal(refund_pct) / Decimal(100)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Validate refund does not exceed booking price
    if refund_amount > booking.total_price:
        logger.error(
            "refund_exceeds_price",
            booking_id=str(booking.id),
            refund_amount=str(refund_amount),
            total_price=str(booking.total_price),
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Refund amount exceeds booking price",
        )

    # Issue Stripe refund or cancellation
    if booking.stripe_payment_intent_id:
        try:
            if refund_pct == 100:
                # Full refund — cancel the payment intent (works for uncaptured and captured)
                await cancel_payment_intent(
                    booking.stripe_payment_intent_id,
                    idempotency_key=f"cancel_{booking.id}",
                )
            elif refund_pct > 0:
                # Partial refund
                refund_cents = int((refund_amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
                await refund_payment_intent(
                    booking.stripe_payment_intent_id,
                    amount_cents=refund_cents,
                    idempotency_key=f"refund_{booking.id}_{refund_pct}pct",
                )
            elif refund_pct == 0:
                # H-004: 0% refund = late cancellation — capture payment for the mechanic
                await capture_payment_intent(booking.stripe_payment_intent_id)
                # AUDIT-15: Mark payment as released since we captured it
                booking.payment_released_at = datetime.now(timezone.utc)
        except StripeServiceError as e:
            logger.error("stripe_cancel_error", error=str(e), booking_id=str(booking.id))
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Payment processing failed. Please try again or contact support.",
            )

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.cancelled_by = cancelled_by
    booking.refund_percentage = refund_pct
    booking.refund_amount = refund_amount

    # R-01: Lock availability and only release if no other active booking references it
    if booking.availability_id:
        avail_result = await db.execute(
            select(Availability).where(Availability.id == booking.availability_id).with_for_update()
        )
        avail = avail_result.scalar_one_or_none()
        if avail:
            other_active = await db.execute(
                select(func.count(Booking.id)).where(
                    Booking.availability_id == booking.availability_id,
                    Booking.id != booking.id,
                    Booking.status != BookingStatus.CANCELLED,
                )
            )
            if (other_active.scalar() or 0) == 0:
                avail.is_booked = False

    await db.flush()

    # Notify the other party about the cancellation
    # H-03: Null check before accessing booking.mechanic.user_id
    if cancelled_by == "buyer":
        notify_user_id = booking.mechanic.user_id if booking.mechanic else None
    else:
        notify_user_id = booking.buyer_id

    if notify_user_id is not None:
        await create_notification(
            db=db,
            user_id=notify_user_id,
            notification_type=NotificationType.BOOKING_CANCELLED,
            title="RDV annule",
            body="Le rendez-vous a ete annule par l'autre partie.",
            data={"booking_id": str(booking.id), "cancelled_by": cancelled_by},
        )

    from app.metrics import BOOKINGS_CANCELLED
    BOOKINGS_CANCELLED.labels(cancelled_by=cancelled_by).inc()

    logger.info(
        "booking_cancelled",
        booking_id=str(booking.id),
        cancelled_by=cancelled_by,
        refund_pct=refund_pct,
        refund_amount=str(refund_amount),
    )
    return {
        "status": "cancelled",
        "cancelled_by": cancelled_by,
        "refund_percentage": refund_pct,
        "refund_amount": str(refund_amount),
    }


@router.patch("/{booking_id}/check-in", response_model=CheckInResponse)
@limiter.limit("10/minute")
async def check_in(
    request: Request,
    booking_id: uuid.UUID,
    body: CheckInRequest,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer confirms mechanic presence and generates a 4-digit code."""
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.AWAITING_MECHANIC_CODE, action="check in")

    # Check time window (tolerance around appointment)
    if not booking.availability:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Availability data missing for this booking",
        )

    slot_dt = datetime.combine(
        booking.availability.date, booking.availability.start_time, tzinfo=timezone.utc
    )
    diff = abs((datetime.now(timezone.utc) - slot_dt).total_seconds())
    tolerance_minutes = settings.BOOKING_CHECK_IN_TOLERANCE_MINUTES
    if diff > tolerance_minutes * 60:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Check-in only allowed within {tolerance_minutes} minutes of the appointment time",
        )

    if body.mechanic_present:
        code = generate_check_in_code()
        booking.check_in_code = hash_check_in_code(code)
        booking.check_in_code_attempts = 0
        booking.check_in_code_generated_at = datetime.now(timezone.utc)
        booking.status = BookingStatus.AWAITING_MECHANIC_CODE
        await db.flush()

        logger.info("check_in_code_generated", booking_id=str(booking.id))
        return CheckInResponse(check_in_code=code)
    else:
        # BUG-004: Explicit state machine validation for no-show path
        validate_transition(booking.status, BookingStatus.DISPUTED, action="report no-show")

        # H-01: No-show dispute protection — check mechanic's last known GPS
        # If mechanic is near the meeting point (within 500m), warn the buyer
        mechanic_nearby = False
        if booking.mechanic_lat is not None and booking.mechanic_lng is not None:
            distance = calculate_distance_km(
                float(booking.mechanic_lat),
                float(booking.mechanic_lng),
                float(booking.meeting_lat),
                float(booking.meeting_lng),
            )
            if distance <= NO_SHOW_DISTANCE_THRESHOLD_KM:
                mechanic_nearby = True
                logger.warning(
                    "no_show_dispute_mechanic_nearby",
                    booking_id=str(booking.id),
                    mechanic_distance_km=round(distance, 3),
                )

        dispute = DisputeCase(
            booking_id=booking.id,
            opened_by=buyer.id,
            reason=DisputeReason.NO_SHOW,
            description="Mechanic did not show up at the meeting point",
            status=DisputeStatus.OPEN,
        )
        db.add(dispute)
        booking.status = BookingStatus.DISPUTED
        # OBS-1: Track dispute creation in Prometheus
        from app.metrics import DISPUTES_OPENED
        DISPUTES_OPENED.labels(reason="no_show").inc()
        await db.flush()

        # Notify mechanic about the no-show report
        if booking.mechanic:
            await create_notification(
                db=db,
                user_id=booking.mechanic.user_id,
                notification_type=NotificationType.NO_SHOW,
                title="Absence signalee",
                body="L'acheteur a signale votre absence au point de rendez-vous.",
                data={"booking_id": str(booking.id)},
            )

        logger.warning("mechanic_no_show_reported", booking_id=str(booking.id), opened_by_user_id=str(buyer.id), opened_by_role=buyer.role.value)
        return CheckInResponse(
            dispute_opened=True,
            mechanic_nearby_warning=mechanic_nearby,
        )


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
    # R-001: Acquire row lock to prevent concurrent code entry race conditions
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CHECK_IN_DONE, action="enter code")

    # Code expiry check (15 minutes)
    if booking.check_in_code_generated_at:
        elapsed = (datetime.now(timezone.utc) - booking.check_in_code_generated_at).total_seconds()
        if elapsed > CHECK_IN_CODE_EXPIRY_SECONDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Code has expired. Please ask the buyer to generate a new code.",
            )

    # Brute-force protection
    if booking.check_in_code_attempts >= MAX_CODE_ATTEMPTS:
        logger.warning(
            "check_in_code_max_attempts_reached",
            booking_id=str(booking.id),
            attempts=booking.check_in_code_attempts,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed attempts. Please ask the buyer to generate a new code.",
        )

    if not body.code or len(body.code) != 6 or not body.code.isdigit():
        raise HTTPException(status_code=400, detail="Code must be 6 digits")

    if not verify_check_in_code(body.code, booking.check_in_code):
        booking.check_in_code_attempts += 1
        await db.flush()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Incorrect code.",
        )

    booking.status = BookingStatus.CHECK_IN_DONE
    booking.check_in_at = datetime.now(timezone.utc)
    # SEC-021: Clear the check-in code after successful validation to prevent reuse
    booking.check_in_code = None
    await db.flush()

    logger.info("check_in_confirmed", booking_id=str(booking.id))
    return {"status": "checked_in"}


@router.patch("/{booking_id}/check-out", response_model=CheckOutResponse)
@limiter.limit("10/hour")
async def check_out(
    request: Request,
    booking_id: uuid.UUID,
    photo_plate: UploadFile,
    photo_odometer: UploadFile,
    entered_odometer_km: int = Form(...),
    checklist_json: str = Form(...),
    entered_plate: str | None = Form(None),
    gps_lat: float | None = Form(None),
    gps_lng: float | None = Form(None),
    additional_photos: list[UploadFile] | None = None,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Mechanic submits inspection results, photos, and checklist. Generates PDF report."""
    additional_photos = additional_photos or []
    user, profile = mechanic
    # I-004: Acquire row lock to prevent concurrent check-out submissions
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CHECK_OUT_DONE, action="check out")

    # Validate form params (since we can't use Pydantic schema with multipart)
    if entered_plate is not None and len(entered_plate) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plate number must be 20 characters or less",
        )

    # Fall back to booking's vehicle_plate when mechanic didn't enter a plate
    effective_plate = entered_plate if entered_plate else booking.vehicle_plate
    if not effective_plate:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Vehicle plate is required",
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
        logger.error("checklist_invalid_json", booking_id=str(booking.id), error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid JSON")
    except ValidationError as e:
        logger.error("checklist_validation_error", booking_id=str(booking.id), error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid data")

    # M-002: Restrict checkout uploads to images only (no PDF)
    _IMAGE_TYPES = {"image/jpeg", "image/png"}
    for photo in [photo_plate, photo_odometer] + additional_photos:
        if photo.content_type not in _IMAGE_TYPES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Only JPEG and PNG images are accepted for inspection photos, got {photo.content_type}",
            )

    # Validate additional photos count (max 10)
    if len(additional_photos) > 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 10 additional photos allowed",
        )

    # Upload photos -- track all uploaded URLs so we can clean up orphans on failure
    uploaded_urls: list[str] = []
    try:
        plate_url = await upload_file(photo_plate, "proofs")
        uploaded_urls.append(plate_url)
        odometer_url = await upload_file(photo_odometer, "proofs")
        uploaded_urls.append(odometer_url)

        # PERF-001: Upload additional photos concurrently instead of sequentially
        additional_photo_urls: list[str] = []
        if additional_photos:
            additional_photo_urls = await asyncio.gather(
                *[upload_file(photo, "proofs") for photo in additional_photos]
            )
            uploaded_urls.extend(additional_photo_urls)
    except ValueError as e:
        # Log orphaned files that were uploaded before the failure
        if uploaded_urls:
            logger.warning(
                "orphaned_files_on_upload_failure",
                booking_id=str(booking.id),
                orphaned_urls=uploaded_urls,
                error=str(e),
            )
        logger.error("upload_validation_failed", booking_id=str(booking.id), error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid data")
    except Exception as e:
        # Unexpected upload error -- log orphaned files before re-raising
        if uploaded_urls:
            logger.warning(
                "orphaned_files_on_upload_failure",
                booking_id=str(booking.id),
                orphaned_urls=uploaded_urls,
                error=str(e),
            )
        raise

    # AUD-007: Check if inspection checklist already exists (idempotency)
    existing_inspection = await db.execute(
        select(InspectionChecklist).where(InspectionChecklist.booking_id == booking.id)
    )
    if existing_inspection.scalar_one_or_none():
        existing_report = await db.execute(
            select(Report).where(Report.booking_id == booking.id)
        )
        report = existing_report.scalar_one_or_none()
        if report:
            return CheckOutResponse(pdf_url=report.pdf_url)

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
            entered_plate=effective_plate,
            entered_odometer_km=entered_odometer_km,
            gps_lat=gps_lat,
            gps_lng=gps_lng,
            additional_photo_urls=additional_photo_urls if additional_photo_urls else None,
            uploaded_by=UploadedBy.MECHANIC,
        )
        db.add(proof)

    # Create inspection checklist (not yet flushed to DB)
    inspection = InspectionChecklist(
        booking_id=booking.id,
        **checklist_data.model_dump(),
    )

    # Generate PDF report BEFORE flushing to DB
    # so that if PDF fails, we haven't saved partial data
    try:
        mechanic_name = get_display_name(user)
        pdf_url = await generate_pdf(
            booking, proof, inspection, mechanic_name,
            additional_photo_urls=additional_photo_urls if additional_photo_urls else None,
        )
    except Exception as e:
        logger.error("pdf_generation_failed", booking_id=str(booking.id), error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate PDF report. Please try again or contact support."
        )

    # PDF succeeded, now persist everything to DB
    db.add(inspection)
    report = Report(booking_id=booking.id, pdf_url=pdf_url)
    db.add(report)
    booking.status = BookingStatus.CHECK_OUT_DONE
    booking.check_out_at = datetime.now(timezone.utc)
    await db.flush()

    # Notify buyer that the report is ready
    await create_notification(
        db=db,
        user_id=booking.buyer_id,
        notification_type=NotificationType.CHECK_OUT_DONE,
        title="Rapport pret !",
        body="Le mecanicien a termine l'inspection. Consultez votre rapport.",
        data={"booking_id": str(booking.id), "pdf_url": pdf_url},
    )

    logger.info("check_out_completed", booking_id=str(booking.id), pdf_url=pdf_url)
    return CheckOutResponse(pdf_url=pdf_url)


@router.patch("/{booking_id}/validate", response_model=dict)
@limiter.limit("10/minute")
async def validate_booking(
    request: Request,
    booking_id: uuid.UUID,
    body: ValidateRequest,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer validates the inspection results, triggering payment release.

    This JSON endpoint is kept for backward compatibility (no photos).
    For dispute submissions with photo evidence, use the /validate-with-photos endpoint.
    """
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.VALIDATED if body.validated else BookingStatus.DISPUTED, action="validate")

    if body.validated:
        booking.status = BookingStatus.VALIDATED
        await db.flush()

        schedule_payment_release(str(booking.id))

        logger.info("booking_validated", booking_id=str(booking.id))
        return {"status": "validated", "payment_release": "scheduled in 2 hours"}
    else:
        # AUD-H07: Check for existing dispute before creating a new one
        existing_dispute = await db.execute(
            select(DisputeCase).where(DisputeCase.booking_id == booking.id)
        )
        if existing_dispute.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "A dispute already exists for this booking")

        dispute = DisputeCase(
            booking_id=booking.id,
            opened_by=buyer.id,
            reason=body.problem_reason,
            description=body.problem_description,
            status=DisputeStatus.OPEN,
        )
        db.add(dispute)
        booking.status = BookingStatus.DISPUTED
        # OBS-1: Track dispute creation in Prometheus
        from app.metrics import DISPUTES_OPENED
        DISPUTES_OPENED.labels(reason=body.problem_reason.value).inc()
        await db.flush()

        # Notify mechanic about the dispute
        if booking.mechanic:
            await create_notification(
                db=db,
                user_id=booking.mechanic.user_id,
                notification_type=NotificationType.BOOKING_DISPUTED,
                title="Litige ouvert",
                body="L'acheteur a conteste le resultat de l'inspection.",
                data={"booking_id": str(booking.id)},
            )

        logger.warning("booking_disputed", booking_id=str(booking.id), reason=body.problem_reason.value, opened_by_user_id=str(buyer.id), opened_by_role=buyer.role.value)
        return {"status": "disputed", "dispute_opened": True}


@router.patch("/{booking_id}/validate-with-photos", response_model=dict)
@limiter.limit("5/minute")
async def validate_booking_with_photos(
    request: Request,
    booking_id: uuid.UUID,
    validated: bool = Form(...),
    problem_reason: str | None = Form(None),
    problem_description: str | None = Form(None),
    photos: list[UploadFile] | None = None,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer validates or disputes with optional photo evidence (FormData endpoint).

    Accepts multipart/form-data with the following fields:
    - validated (bool): True to approve, False to open a dispute
    - problem_reason (str): Required when validated=False. One of the DisputeReason values.
    - problem_description (str): Required when validated=False. Free-text description (max 1000 chars).
    - photos (files): Optional, up to 5 JPEG/PNG images as evidence for the dispute.
    """
    booking = await _get_booking(db, booking_id, lock=True)

    if booking.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.VALIDATED if validated else BookingStatus.DISPUTED, action="validate")

    if validated:
        booking.status = BookingStatus.VALIDATED
        await db.flush()

        schedule_payment_release(str(booking.id))

        logger.info("booking_validated", booking_id=str(booking.id))
        return {"status": "validated", "payment_release": "scheduled in 2 hours"}
    else:
        if not problem_reason:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="problem_reason is required when validated is False",
            )
        if not problem_description:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="problem_description is required when validated is False",
            )
        if len(problem_description) > 1000:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="problem_description must be 1000 characters or less",
            )

        # Validate and convert reason string to enum
        try:
            reason_enum = DisputeReason(problem_reason)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid dispute reason. Must be one of: no_show, wrong_info, rude_behavior, other",
            )

        # AUD-H07: Check for existing dispute before creating a new one
        existing_dispute = await db.execute(
            select(DisputeCase).where(DisputeCase.booking_id == booking.id)
        )
        if existing_dispute.scalar_one_or_none():
            raise HTTPException(status.HTTP_409_CONFLICT, "A dispute already exists for this booking")

        # Upload dispute photos (max 5)
        photo_urls: list[str] = []
        # M-05: Track failed photo uploads to include in response
        failed_photos: list[str] = []
        upload_photos = photos or []
        if len(upload_photos) > 5:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Maximum 5 photos allowed",
            )
        allowed_content_types = {"image/jpeg", "image/png"}
        for photo in upload_photos:
            if photo.content_type not in allowed_content_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Invalid photo type '{photo.content_type}'. Only JPEG and PNG are accepted.",
                )
        for photo in upload_photos:
            try:
                url = await upload_file(photo, "disputes")
                photo_urls.append(url)
            except ValueError as e:
                logger.error("dispute_photo_upload_failed", booking_id=str(booking.id), error=str(e))
                failed_photos.append(photo.filename or "unknown")

        dispute = DisputeCase(
            booking_id=booking.id,
            opened_by=buyer.id,
            reason=reason_enum,
            description=problem_description,
            photo_urls=photo_urls if photo_urls else None,
            status=DisputeStatus.OPEN,
        )
        db.add(dispute)
        booking.status = BookingStatus.DISPUTED
        # OBS-1: Track dispute creation in Prometheus
        from app.metrics import DISPUTES_OPENED
        DISPUTES_OPENED.labels(reason=reason_enum.value).inc()
        await db.flush()

        # Notify mechanic about the dispute
        if booking.mechanic:
            await create_notification(
                db=db,
                user_id=booking.mechanic.user_id,
                notification_type=NotificationType.BOOKING_DISPUTED,
                title="Litige ouvert",
                body="L'acheteur a conteste le resultat de l'inspection.",
                data={"booking_id": str(booking.id)},
            )

        logger.warning(
            "booking_disputed",
            booking_id=str(booking.id),
            reason=problem_reason,
            opened_by_user_id=str(buyer.id),
            opened_by_role=buyer.role.value,
            photo_count=len(photo_urls),
            failed_photo_count=len(failed_photos),
        )
        # M-05: Include upload warnings in the response
        response: dict = {"status": "disputed", "dispute_opened": True, "photo_count": len(photo_urls)}
        if failed_photos:
            response["upload_warnings"] = [f"Failed to upload: {name}" for name in failed_photos]
        return response


@router.get("/me")
@limiter.limit(LIST_RATE_LIMIT)
async def list_my_bookings(
    request: Request,
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
):
    """List all bookings for the current user (buyer, mechanic, or admin).

    AUD-M04: The X-Total-Count response header contains the total number of
    bookings matching the query (before pagination), so the mobile app can
    display pagination controls without changing the JSON response format.
    """
    if user.role == UserRole.BUYER:
        base_filter = Booking.buyer_id == user.id
        result = await db.execute(
            select(Booking)
            .where(base_filter)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
                selectinload(Booking.reviews),
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        # AUD-M04: Total count for pagination header
        total = (await db.execute(
            select(func.count()).select_from(select(Booking.id).where(base_filter).subquery())
        )).scalar() or 0
    elif user.role == UserRole.ADMIN:
        # Admin sees all bookings
        result = await db.execute(
            select(Booking)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
                selectinload(Booking.reviews),
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        total = (await db.execute(
            select(func.count()).select_from(select(Booking.id).subquery())
        )).scalar() or 0
    else:
        # Mechanic
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if not profile:
            response.headers["X-Total-Count"] = "0"
            return []

        base_filter = Booking.mechanic_id == profile.id
        result = await db.execute(
            select(Booking)
            .where(base_filter)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
                selectinload(Booking.reviews),
            )
            .order_by(Booking.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        total = (await db.execute(
            select(func.count()).select_from(select(Booking.id).where(base_filter).subquery())
        )).scalar() or 0

    response.headers["X-Total-Count"] = str(total)
    return [_serialize_booking(b, user.role) for b in result.scalars().all()]


@router.get("/{booking_id}")
@limiter.limit("60/minute")
async def get_booking(
    request: Request,
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


@router.patch("/{booking_id}/location")
@limiter.limit("60/minute")
async def update_location(
    request: Request,
    booking_id: uuid.UUID,
    body: LocationUpdate,
    # O-3: Use get_current_mechanic to enforce suspension check (was get_current_user)
    mechanic_tuple: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Mechanic sends their current GPS position for real-time tracking."""
    user, mechanic = mechanic_tuple

    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Only the mechanic of this booking can update location
    if booking.mechanic_id != mechanic.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    # Must be CONFIRMED status
    if booking.status != BookingStatus.CONFIRMED:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tracking only available for confirmed bookings",
        )

    # Check time window: booking slot +/- 15 min
    if booking.availability_id:
        avail_result = await db.execute(
            select(Availability).where(Availability.id == booking.availability_id)
        )
        avail = avail_result.scalar_one_or_none()
        if avail:
            now = datetime.now(timezone.utc)
            slot_start = datetime.combine(avail.date, avail.start_time, tzinfo=timezone.utc)
            slot_end = datetime.combine(avail.date, avail.end_time, tzinfo=timezone.utc)
            window_start = slot_start - timedelta(minutes=15)
            window_end = slot_end + timedelta(minutes=15)
            if not (window_start <= now <= window_end):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Tracking only available during booking time window",
                )

    booking.mechanic_lat = body.lat
    booking.mechanic_lng = body.lng
    booking.mechanic_location_updated_at = datetime.now(timezone.utc)
    await db.flush()
    return {"status": "ok"}


@router.get("/{booking_id}/location")
@limiter.limit("120/minute")
async def get_location(
    request: Request,
    booking_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Buyer gets the mechanic's current GPS position for real-time tracking."""
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # M-09: Admin bypass + buyer of this booking can view location
    if user.role != UserRole.ADMIN and booking.buyer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if booking.mechanic_lat is None or booking.mechanic_lng is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No location available")

    # AUDIT-16: Round to 3 decimals (~111m precision) — sufficient for real-time
    # tracking without exposing the mechanic's exact position to the metre.
    return {
        "lat": round(float(booking.mechanic_lat), 3),
        "lng": round(float(booking.mechanic_lng), 3),
        "updated_at": booking.mechanic_location_updated_at.isoformat() if booking.mechanic_location_updated_at else None,
    }


async def _get_booking(db: AsyncSession, booking_id: uuid.UUID, lock: bool = False) -> Booking:
    """Fetch a booking by ID or raise 404. Eagerly loads relationships used by route handlers.

    Args:
        lock: If True, acquire a row-level lock (SELECT FOR UPDATE) to prevent
              concurrent modifications (e.g. validate + dispute race condition).
    """
    # NOTE: with_for_update() locks only the bookings row, not related rows
    # loaded via selectinload (availability, mechanic, buyer). For endpoints
    # that modify availability.is_booked (cancel, refuse), there is a theoretical
    # race with concurrent create_booking. Mitigated by: (1) booking state machine
    # prevents invalid transitions, (2) low probability of exact same slot being
    # cancelled and rebooked simultaneously. Fixing with joinedload or separate
    # FOR UPDATE on availability would risk deadlocks due to lock ordering.
    stmt = (
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.availability),
            selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
            selectinload(Booking.buyer),
            selectinload(Booking.reviews),
        )
    )
    if lock:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking
