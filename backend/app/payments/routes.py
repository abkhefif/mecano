from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_admin, get_current_mechanic
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import BookingStatus, DisputeReason, DisputeStatus
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from app.services.penalties import apply_no_show_penalty
from app.schemas.payment import DashboardLinkResponse, DisputeResolveRequest, OnboardResponse
from app.utils.booking_state import validate_transition
from app.utils.rate_limit import limiter
from app.services.stripe_service import (
    cancel_payment_intent,
    capture_payment_intent,
    create_connect_account,
    create_login_link,
    verify_webhook_signature,
)

logger = structlog.get_logger()
router = APIRouter()


@router.post("/onboard-mechanic", response_model=OnboardResponse)
async def onboard_mechanic(
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe Connect Express account for the mechanic."""
    user, profile = mechanic

    if profile.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stripe account already created",
        )

    result = await create_connect_account(user.email)
    profile.stripe_account_id = result["account_id"]
    await db.flush()

    logger.info("stripe_account_created", mechanic_id=str(profile.id))
    return OnboardResponse(onboarding_url=result["onboarding_url"])


@router.get("/mechanic-dashboard", response_model=DashboardLinkResponse)
async def mechanic_dashboard(
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
):
    """Get a Stripe Express Dashboard login link."""
    _, profile = mechanic

    if not profile.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No Stripe account found. Please complete onboarding first.",
        )

    url = await create_login_link(profile.stripe_account_id)
    return DashboardLinkResponse(dashboard_url=url)


@router.post("/webhooks/stripe")
@limiter.limit("100/minute")
async def stripe_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Handle Stripe webhook events."""
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    event_id = event["id"]
    event_type = event["type"]

    # Idempotency: skip already-processed events
    existing = await db.execute(
        select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
    )
    if existing.scalar_one_or_none():
        logger.info("stripe_webhook_duplicate_skipped", event_id=event_id)
        return {"status": "already_processed"}

    logger.info("stripe_webhook_received", event_type=event_type, event_id=event_id)

    if event_type == "payment_intent.succeeded":
        intent = event["data"]["object"]
        intent_id = intent["id"]
        result = await db.execute(
            select(Booking).where(Booking.stripe_payment_intent_id == intent_id)
        )
        booking = result.scalar_one_or_none()
        if booking:
            logger.info("payment_intent_succeeded", booking_id=str(booking.id))

    elif event_type == "payment_intent.payment_failed":
        intent = event["data"]["object"]
        intent_id = intent["id"]
        result = await db.execute(
            select(Booking)
            .where(Booking.stripe_payment_intent_id == intent_id)
            .options(selectinload(Booking.availability))
        )
        booking = result.scalar_one_or_none()
        if booking and booking.status == BookingStatus.PENDING_ACCEPTANCE:
            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = datetime.now(timezone.utc)
            if booking.availability:
                booking.availability.is_booked = False
            await db.flush()
            logger.warning("payment_failed_booking_cancelled", booking_id=str(booking.id))

    elif event_type == "charge.dispute.created":
        logger.warning("stripe_dispute_created", event_data=str(event["data"]["object"].get("id")))

    # Record event as processed for idempotency
    db.add(ProcessedWebhookEvent(event_id=event_id))
    await db.flush()

    return {"status": "ok"}


@router.patch("/disputes/resolve", response_model=dict)
async def resolve_dispute(
    body: DisputeResolveRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin resolves a dispute. Resolution: 'buyer' (refund) or 'mechanic' (release payment)."""
    result = await db.execute(
        select(DisputeCase).where(DisputeCase.id == body.dispute_id)
    )
    dispute = result.scalar_one_or_none()
    if not dispute:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dispute not found")

    if dispute.status != DisputeStatus.OPEN:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dispute is already resolved")

    booking_result = await db.execute(
        select(Booking)
        .where(Booking.id == dispute.booking_id)
        .options(selectinload(Booking.mechanic))
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if body.resolution == "buyer":
        # Refund to buyer
        new_status = BookingStatus.CANCELLED
        validate_transition(booking.status, new_status)
        if booking.stripe_payment_intent_id:
            await cancel_payment_intent(booking.stripe_payment_intent_id)
        dispute.status = DisputeStatus.RESOLVED_BUYER
        booking.status = new_status

        # Apply no-show penalty if dispute reason was mechanic no-show
        if dispute.reason == DisputeReason.NO_SHOW and booking.mechanic:
            await apply_no_show_penalty(db, booking.mechanic)
    else:
        # Release payment to mechanic
        new_status = BookingStatus.COMPLETED
        validate_transition(booking.status, new_status)
        if booking.stripe_payment_intent_id:
            await capture_payment_intent(booking.stripe_payment_intent_id)
        dispute.status = DisputeStatus.RESOLVED_MECHANIC
        booking.status = new_status
        booking.payment_released_at = datetime.now(timezone.utc)

    dispute.resolved_at = datetime.now(timezone.utc)
    dispute.resolved_by_admin = admin.id
    dispute.resolution_notes = body.resolution_notes

    await db.flush()
    logger.info("dispute_resolved", dispute_id=str(body.dispute_id), resolution=body.resolution)
    return {"status": "resolved", "resolution": body.resolution}
