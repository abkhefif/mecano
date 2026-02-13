import hmac
import json
import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, TypedDict

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, UploadFile, status
from pydantic import ValidationError
from sqlalchemy import select
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
from app.services.stripe_service import cancel_payment_intent, create_payment_intent, refund_payment_intent
from app.config import settings
from app.utils.code_generator import generate_check_in_code
from app.utils.display_name import get_display_name
from app.utils.geo import calculate_distance_km
from app.utils.booking_state import validate_transition
from app.utils.rate_limit import CODE_ENTRY_RATE_LIMIT, LIST_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()

MAX_CODE_ATTEMPTS = settings.MAX_CHECK_IN_CODE_ATTEMPTS


class SerializedBooking(TypedDict, total=False):
    """Shape returned by _serialize_booking. Includes base schema fields plus
    dynamically added slot/contact/refuse fields. Keys depend on the user role
    and booking state; ``total=False`` reflects that optional keys may be absent."""
    slot_date: str
    slot_start_time: str
    slot_end_time: str
    refuse_reason: str | None
    proposed_time: str | None
    contact_phone: str | None


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

    # If buyer chose a sub-slot within a larger availability window, split it
    booked_slot = availability  # by default, book the whole slot
    if body.slot_start_time:
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

    # Check booking is sufficiently in the future
    slot_datetime = datetime.combine(booked_slot.date, booked_slot.start_time, tzinfo=timezone.utc)
    if slot_datetime - datetime.now(timezone.utc) < timedelta(hours=settings.BOOKING_MINIMUM_ADVANCE_HOURS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Booking must be at least {settings.BOOKING_MINIMUM_ADVANCE_HOURS} hours in advance",
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
        from sqlalchemy import and_
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

    return BookingCreateResponse(
        booking=BookingResponse.model_validate(booking),
        client_secret=intent["client_secret"],
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
    booking = await _get_booking(db, booking_id)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CONFIRMED, action="accept")

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
    booking = await _get_booking(db, booking_id)

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
        await cancel_payment_intent(booking.stripe_payment_intent_id)

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.refuse_reason = body.reason.value
    booking.proposed_time = body.proposed_time
    booking.cancelled_by = "mechanic"
    booking.refund_percentage = 100
    booking.refund_amount = refund_amount

    if booking.availability:
        booking.availability.is_booked = False

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
    """Cancel a booking (buyer or mechanic). Applies refund policy based on time to appointment."""
    booking = await _get_booking(db, booking_id)

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

    # Issue Stripe refund or cancellation
    if booking.stripe_payment_intent_id:
        if refund_pct == 100:
            # Full refund — cancel the payment intent (works for uncaptured and captured)
            await cancel_payment_intent(booking.stripe_payment_intent_id)
        elif refund_pct > 0:
            # Partial refund
            refund_cents = int(refund_amount * 100)
            await refund_payment_intent(booking.stripe_payment_intent_id, amount_cents=refund_cents)
        # refund_pct == 0: no refund, no Stripe action needed

    booking.status = BookingStatus.CANCELLED
    booking.cancelled_at = datetime.now(timezone.utc)
    booking.cancelled_by = cancelled_by
    booking.refund_percentage = refund_pct
    booking.refund_amount = refund_amount

    # Release the availability slot
    if booking.availability:
        booking.availability.is_booked = False

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
    buyer: User = Depends(get_current_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer confirms mechanic presence and generates a 4-digit code."""
    booking = await _get_booking(db, booking_id)

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
        booking.check_in_code = code
        booking.check_in_code_attempts = 0
        booking.check_in_code_generated_at = datetime.now(timezone.utc)
        booking.status = BookingStatus.AWAITING_MECHANIC_CODE
        await db.flush()

        logger.info("check_in_code_generated", booking_id=str(booking.id))
        return CheckInResponse(check_in_code=code)
    else:
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
            if distance <= 0.5:  # 500 meters
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
    booking = await _get_booking(db, booking_id)

    if booking.mechanic_id != profile.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your booking")

    validate_transition(booking.status, BookingStatus.CHECK_IN_DONE, action="enter code")

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

    if not body.code or len(body.code) != 4 or not body.code.isdigit():
        raise HTTPException(status_code=400, detail="Code must be 4 digits")

    if not hmac.compare_digest(booking.check_in_code, body.code):
        booking.check_in_code_attempts += 1
        await db.flush()
        remaining = MAX_CODE_ATTEMPTS - booking.check_in_code_attempts
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Incorrect code. {remaining} attempts remaining.",
        )

    booking.status = BookingStatus.CHECK_IN_DONE
    booking.check_in_at = datetime.now(timezone.utc)
    # SEC-021: Clear the check-in code after successful validation to prevent reuse
    booking.check_in_code = None
    await db.flush()

    logger.info("check_in_confirmed", booking_id=str(booking.id))
    return {"status": "checked_in"}


@router.patch("/{booking_id}/check-out", response_model=CheckOutResponse)
async def check_out(
    booking_id: uuid.UUID,
    photo_plate: UploadFile,
    photo_odometer: UploadFile,
    entered_odometer_km: int,
    checklist_json: str,
    entered_plate: str | None = None,
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

    validate_transition(booking.status, BookingStatus.CHECK_OUT_DONE, action="check out")

    # Validate form params (since we can't use Pydantic schema with multipart)
    if entered_plate is not None and len(entered_plate) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plate number must be 20 characters or less",
        )

    # Fall back to booking's vehicle_plate when mechanic didn't enter a plate
    effective_plate = entered_plate if entered_plate else booking.vehicle_plate
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Donnees invalides")

    # Upload photos
    try:
        plate_url = await upload_file(photo_plate, "proofs")
        odometer_url = await upload_file(photo_odometer, "proofs")
    except ValueError as e:
        logger.error("upload_validation_failed", booking_id=str(booking.id), error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Donnees invalides")

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
        pdf_url = await generate_pdf(booking, proof, inspection, mechanic_name)
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
    buyer: User = Depends(get_current_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer validates the inspection results, triggering payment release.

    This JSON endpoint is kept for backward compatibility (no photos).
    For dispute submissions with photo evidence, use the /validate-with-photos endpoint.
    """
    booking = await _get_booking(db, booking_id)

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
    validated: bool,
    problem_reason: str | None = None,
    problem_description: str | None = None,
    photos: list[UploadFile] | None = None,
    buyer: User = Depends(get_current_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Buyer validates or disputes with optional photo evidence (FormData endpoint).

    Accepts multipart/form-data with the following fields:
    - validated (bool): True to approve, False to open a dispute
    - problem_reason (str): Required when validated=False. One of the DisputeReason values.
    - problem_description (str): Required when validated=False. Free-text description (max 1000 chars).
    - photos (files): Optional, up to 5 JPEG/PNG images as evidence for the dispute.
    """
    booking = await _get_booking(db, booking_id)

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
                detail=f"Invalid dispute reason: {problem_reason}",
            )

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
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
                selectinload(Booking.reviews),
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
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
                selectinload(Booking.reviews),
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
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
                selectinload(Booking.reviews),
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


@router.patch("/{booking_id}/location")
@limiter.limit("60/minute")
async def update_location(
    request: Request,
    booking_id: uuid.UUID,
    body: LocationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mechanic sends their current GPS position for real-time tracking."""
    booking = await db.get(Booking, booking_id)
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    # Only the mechanic of this booking can update location
    profile_result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.user_id == user.id)
    )
    mechanic = profile_result.scalar_one_or_none()
    if not mechanic or booking.mechanic_id != mechanic.id:
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
async def get_location(
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

    return {
        "lat": float(booking.mechanic_lat),
        "lng": float(booking.mechanic_lng),
        "updated_at": booking.mechanic_location_updated_at.isoformat() if booking.mechanic_location_updated_at else None,
    }


async def _get_booking(db: AsyncSession, booking_id: uuid.UUID) -> Booking:
    """Fetch a booking by ID or raise 404. Eagerly loads relationships used by route handlers."""
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(
            selectinload(Booking.availability),
            selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
            selectinload(Booking.buyer),
            selectinload(Booking.reviews),
        )
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")
    return booking
