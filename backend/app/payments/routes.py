import asyncio
import re
from datetime import datetime, timezone

import stripe
import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Request, status

from app.config import settings
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_admin, get_current_mechanic, get_current_user
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
    StripeServiceError,
    cancel_payment_intent,
    capture_payment_intent,
    create_connect_account,
    create_login_link,
    detach_payment_method,
    list_payment_methods,
    refund_payment_intent,
    verify_webhook_signature,
)

logger = structlog.get_logger()
router = APIRouter()


@router.post("/onboard-mechanic", response_model=OnboardResponse)
@limiter.limit("10/hour")
async def onboard_mechanic(
    request: Request,
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
@limiter.limit("30/minute")
async def mechanic_dashboard(
    request: Request,
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
    # R-004: Reject oversized webhook payloads before reading the body
    MAX_WEBHOOK_PAYLOAD_BYTES = 65_536  # 64 KB
    content_length = request.headers.get("content-length")
    try:
        if content_length and int(content_length) > MAX_WEBHOOK_PAYLOAD_BYTES:
            raise HTTPException(status_code=413, detail="Payload too large")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid Content-Length header")

    payload = await request.body()
    if len(payload) > MAX_WEBHOOK_PAYLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Payload too large")

    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = verify_webhook_signature(payload, sig_header)
    except stripe.SignatureVerificationError as e:
        logger.error("stripe_webhook_signature_failed", error=str(e))
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid signature")

    event_id = event["id"]
    event_type = event["type"]

    # SEC-011: Never log the raw event payload or data.object — it may contain
    # sensitive payment data (card fingerprints, tokens, customer details).
    # Only log safe fields: event_type, event_id, booking_id, and amount.

    # Idempotency: skip already-processed events
    existing = await db.execute(
        select(ProcessedWebhookEvent).where(ProcessedWebhookEvent.event_id == event_id)
    )
    if existing.scalar_one_or_none():
        logger.info("stripe_webhook_duplicate_skipped", event_id=event_id)
        return {"status": "already_processed"}

    # BUG-005: Insert idempotency record BEFORE processing to close the race window.
    # If processing fails, the record stays and the event won't be retried — but Stripe
    # will re-deliver it, and since it's already marked, it will be skipped as duplicate.
    # This is safer than double-processing side effects (duplicate refunds, etc.).
    try:
        db.add(ProcessedWebhookEvent(event_id=event_id))
        await db.flush()
    except IntegrityError:
        # PAY-DEDUP: Concurrent request already inserted this event_id
        await db.rollback()
        logger.info("stripe_webhook_duplicate_race", event_id=event_id)
        return {"status": "already_processed"}

    logger.info("stripe_webhook_received", event_type=event_type, event_id=event_id)

    if event_type == "payment_intent.succeeded":
        # This fires after capture (payment released to mechanic).
        # Acts as redundant confirmation alongside the scheduler.
        intent = event["data"]["object"]
        intent_id = intent["id"]
        # AUD4-005: Use FOR UPDATE to prevent race with scheduler's release_payment
        result = await db.execute(
            select(Booking)
            .where(Booking.stripe_payment_intent_id == intent_id)
            .with_for_update(skip_locked=True)
        )
        booking = result.scalar_one_or_none()
        if booking:
            if booking.status == BookingStatus.VALIDATED:
                booking.status = BookingStatus.COMPLETED
                booking.payment_released_at = datetime.now(timezone.utc)
                await db.flush()
                logger.info("payment_captured_booking_completed", booking_id=str(booking.id))
            else:
                logger.info("payment_intent_succeeded", booking_id=str(booking.id), status=booking.status.value)

    elif event_type == "payment_intent.amount_capturable_updated":
        # This fires when the customer's card is authorized (hold placed).
        # The booking can now proceed with mechanic acceptance.
        intent = event["data"]["object"]
        intent_id = intent["id"]
        result = await db.execute(
            select(Booking).where(Booking.stripe_payment_intent_id == intent_id)
        )
        booking = result.scalar_one_or_none()
        if booking:
            logger.info("payment_authorized", booking_id=str(booking.id), amount=intent.get("amount_capturable"))

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
            # I-002: Payment failure is buyer-side (card declined), attribute to buyer
            booking.cancelled_by = "buyer"
            if booking.availability:
                booking.availability.is_booked = False
            await db.flush()
            logger.warning("payment_failed_booking_cancelled", booking_id=str(booking.id))

    elif event_type == "payment_intent.canceled":
        intent = event["data"]["object"]
        intent_id = intent["id"]
        result = await db.execute(
            select(Booking)
            .where(Booking.stripe_payment_intent_id == intent_id)
            .options(selectinload(Booking.availability))
        )
        booking = result.scalar_one_or_none()
        if booking and booking.status in (BookingStatus.PENDING_ACCEPTANCE, BookingStatus.CONFIRMED):
            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = datetime.now(timezone.utc)
            # B-002: Payment cancellation is buyer-side, attribute to buyer
            booking.cancelled_by = "buyer"
            if booking.availability:
                booking.availability.is_booked = False
            await db.flush()
            logger.info("payment_canceled_booking_cancelled", booking_id=str(booking.id))

    elif event_type == "charge.refund.created":
        refund = event["data"]["object"]
        intent_id = refund.get("payment_intent")
        if intent_id:
            result = await db.execute(
                select(Booking).where(Booking.stripe_payment_intent_id == intent_id)
            )
            booking = result.scalar_one_or_none()
            if booking:
                logger.info("refund_created", booking_id=str(booking.id), amount=refund.get("amount"))

    elif event_type == "account.updated":
        account_obj = event["data"]["object"]
        account_id = account_obj.get("id")
        charges_enabled = account_obj.get("charges_enabled", False)
        payouts_enabled = account_obj.get("payouts_enabled", False)

        if charges_enabled and payouts_enabled:
            # Stripe Connect account is fully onboarded
            result = await db.execute(
                select(MechanicProfile).where(
                    MechanicProfile.stripe_account_id == account_id
                )
            )
            profile = result.scalar_one_or_none()
            if profile:
                # Mark mechanic as active after successful Stripe onboarding
                # I-002: Only auto-activate if identity has been verified
                if not profile.is_active and profile.is_identity_verified:
                    profile.is_active = True
                    await db.flush()
                logger.info(
                    "stripe_account_fully_onboarded",
                    account_id=account_id,
                    mechanic_profile_id=str(profile.id),
                )
            else:
                logger.warning(
                    "stripe_account_updated_no_profile",
                    account_id=account_id,
                )
        else:
            logger.info(
                "stripe_account_updated_not_fully_onboarded",
                account_id=account_id,
                charges_enabled=charges_enabled,
                payouts_enabled=payouts_enabled,
            )

    elif event_type == "charge.dispute.created":
        # PAY-R03: Create a DisputeCase when Stripe opens a dispute
        dispute_obj = event["data"]["object"]
        dispute_pi = dispute_obj.get("payment_intent")
        dispute_reason = dispute_obj.get("reason", "unknown")
        stripe_dispute_id = dispute_obj.get("id")

        logger.warning(
            "stripe_dispute_created",
            event_type=event_type,
            dispute_id=str(stripe_dispute_id),
            dispute_reason=dispute_reason,
            dispute_amount=dispute_obj.get("amount"),
            dispute_currency=dispute_obj.get("currency"),
        )

        if dispute_pi:
            dispute_booking_result = await db.execute(
                select(Booking).where(Booking.stripe_payment_intent_id == dispute_pi)
            )
            dispute_booking = dispute_booking_result.scalar_one_or_none()
            if dispute_booking:
                # Only create if no existing dispute for this booking
                existing_dispute = await db.execute(
                    select(DisputeCase).where(DisputeCase.booking_id == dispute_booking.id)
                )
                if not existing_dispute.scalar_one_or_none():
                    # Map Stripe reason to our DisputeReason enum
                    reason_map = {
                        "product_not_received": DisputeReason.NO_SHOW,
                        "product_unacceptable": DisputeReason.WRONG_INFO,
                    }
                    mapped_reason = reason_map.get(dispute_reason, DisputeReason.OTHER)
                    new_dispute = DisputeCase(
                        booking_id=dispute_booking.id,
                        opened_by=dispute_booking.buyer_id,
                        reason=mapped_reason,
                        description=f"Auto-created from Stripe dispute {stripe_dispute_id}: {dispute_reason}",
                    )
                    db.add(new_dispute)
                    await db.flush()
                    logger.info(
                        "dispute_case_auto_created",
                        booking_id=str(dispute_booking.id),
                        stripe_dispute_id=stripe_dispute_id,
                    )
                else:
                    logger.info(
                        "dispute_case_already_exists",
                        booking_id=str(dispute_booking.id),
                    )

    elif event_type == "charge.refund.updated":
        refund = event["data"]["object"]
        intent_id = refund.get("payment_intent")
        refund_status = refund.get("status")
        if intent_id:
            result = await db.execute(
                select(Booking).where(Booking.stripe_payment_intent_id == intent_id)
            )
            booking = result.scalar_one_or_none()
            if booking:
                logger.info("refund_updated", booking_id=str(booking.id), refund_status=refund_status)

    elif event_type == "charge.refund.failed":
        refund = event["data"]["object"]
        intent_id = refund.get("payment_intent")
        if intent_id:
            result = await db.execute(
                select(Booking).where(Booking.stripe_payment_intent_id == intent_id)
            )
            booking = result.scalar_one_or_none()
            if booking:
                logger.error(
                    "refund_failed",
                    booking_id=str(booking.id),
                    failure_reason=refund.get("failure_reason"),
                )

    elif event_type in ("charge.dispute.closed", "charge.dispute.funds_withdrawn", "charge.dispute.funds_reinstated"):
        # PAY-DISP: Handle dispute lifecycle events
        dispute_obj = event["data"]["object"]
        stripe_dispute_id = dispute_obj.get("id")
        dispute_status = dispute_obj.get("status")
        dispute_pi = dispute_obj.get("payment_intent")
        logger.info(
            "stripe_dispute_lifecycle",
            event_type=event_type,
            dispute_id=str(stripe_dispute_id),
            dispute_status=dispute_status,
        )
        if dispute_pi:
            result = await db.execute(
                select(Booking).where(Booking.stripe_payment_intent_id == dispute_pi)
            )
            booking = result.scalar_one_or_none()
            if booking:
                existing_dispute = await db.execute(
                    select(DisputeCase).where(DisputeCase.booking_id == booking.id)
                )
                dispute_case = existing_dispute.scalar_one_or_none()
                if dispute_case and dispute_case.status not in (DisputeStatus.CLOSED, DisputeStatus.RESOLVED_BUYER, DisputeStatus.RESOLVED_MECHANIC):
                    if dispute_status == "won":
                        dispute_case.status = DisputeStatus.CLOSED
                        dispute_case.resolution_notes = "Dispute won — funds returned to platform"
                    elif dispute_status == "lost":
                        dispute_case.status = DisputeStatus.CLOSED
                        dispute_case.resolution_notes = "Dispute lost — funds withdrawn by cardholder"
                    await db.flush()

    return {"status": "ok"}


@router.patch("/disputes/resolve", response_model=dict)
@limiter.limit("30/minute")
async def resolve_dispute(
    request: Request,
    body: DisputeResolveRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Admin resolves a dispute. Resolution: 'buyer' (refund) or 'mechanic' (release payment)."""
    result = await db.execute(
        select(DisputeCase)
        .where(DisputeCase.id == body.dispute_id)
        .with_for_update()
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
        .with_for_update()
    )
    booking = booking_result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    try:
        if body.resolution == "buyer":
            # FIN-08: Use refund_payment_intent which handles both captured (refund)
            # and uncaptured (cancel) PIs correctly, including partial refunds
            new_status = BookingStatus.CANCELLED
            validate_transition(booking.status, new_status)
            if booking.stripe_payment_intent_id:
                await refund_payment_intent(
                    booking.stripe_payment_intent_id,
                    idempotency_key=f"dispute_resolve_{dispute.id}",
                )
                from app.metrics import PAYMENTS_REFUNDED
                PAYMENTS_REFUNDED.inc()
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
    except StripeServiceError as e:
        logger.error("stripe_dispute_resolve_error", error=str(e), dispute_id=str(body.dispute_id))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Payment processing failed. Please try again or contact support.",
        )

    dispute.resolved_at = datetime.now(timezone.utc)
    dispute.resolved_by_admin = admin.id
    dispute.resolution_notes = body.resolution_notes

    # ADMIN-R01: Audit log
    from app.models.audit_log import AuditLog
    db.add(AuditLog(
        action=f"resolve_dispute_{body.resolution}",
        admin_user_id=admin.id,
        detail=body.resolution_notes,
        metadata_json={"dispute_id": str(body.dispute_id), "resolution": body.resolution},
    ))

    await db.flush()
    logger.info("dispute_resolved", dispute_id=str(body.dispute_id), resolution=body.resolution)
    return {"status": "resolved", "resolution": body.resolution}


@router.get("/methods")
@limiter.limit("30/minute")
async def get_payment_methods(
    request: Request,
    user: User = Depends(get_current_user),
):
    """List saved payment methods for the current user."""
    if not user.stripe_customer_id:
        return []

    try:
        methods = await list_payment_methods(user.stripe_customer_id)
        return methods
    except Exception as e:
        logger.error("list_payment_methods_failed", error=str(e), user_id=str(user.id))
        raise HTTPException(status_code=500, detail="Failed to retrieve payment methods")


@router.delete("/methods/{payment_method_id}")
@limiter.limit("10/minute")
async def delete_payment_method(
    request: Request,
    payment_method_id: str = Path(..., max_length=100),
    user: User = Depends(get_current_user),
):
    """Remove a saved payment method."""
    if not user.stripe_customer_id:
        raise HTTPException(status_code=404, detail="No payment methods found")

    # Validate payment_method_id format (pm_xxxxx)
    if not re.match(r"^pm_[a-zA-Z0-9]{10,50}$", payment_method_id):
        raise HTTPException(status_code=400, detail="Invalid payment method ID")

    # SEC-003: Verify the payment method belongs to this user before detaching.
    # FINDING-H03: Differentiate between timeout, not-found, and unexpected errors
    # so that transient network failures do not surface as misleading 404 responses.
    try:
        pm = await asyncio.wait_for(
            asyncio.to_thread(
                stripe.PaymentMethod.retrieve,
                payment_method_id,
                api_key=settings.STRIPE_SECRET_KEY,
            ),
            timeout=15.0,
        )
    except asyncio.TimeoutError:
        logger.error("stripe_pm_retrieve_timeout", pm_id=payment_method_id)
        raise HTTPException(status_code=503, detail="Payment service temporarily unavailable")
    except stripe.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Payment method not found")
    except Exception as e:
        logger.error("stripe_pm_retrieve_error", error=str(e), pm_id=payment_method_id)
        raise HTTPException(status_code=500, detail="Failed to retrieve payment method")

    if pm.customer != user.stripe_customer_id:
        raise HTTPException(status_code=403, detail="Payment method does not belong to you")

    try:
        await detach_payment_method(payment_method_id)
        return {"status": "deleted"}
    except Exception as e:
        logger.error("detach_payment_method_failed", error=str(e), pm_id=payment_method_id)
        raise HTTPException(status_code=500, detail="Failed to remove payment method")
