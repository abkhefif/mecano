from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.enums import BookingStatus
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from app.services.penalties import apply_no_show_penalty
from app.services.stripe_service import cancel_payment_intent, capture_payment_intent

logger = structlog.get_logger()

scheduler = AsyncIOScheduler()


async def release_payment(booking_id: str) -> None:
    """Capture the held payment and transfer to mechanic, 2h after validation."""
    async with async_session() as db:
        result = await db.execute(
            select(Booking).where(Booking.id == booking_id)
        )
        booking = result.scalar_one_or_none()
        if not booking:
            logger.error("release_payment_booking_not_found", booking_id=booking_id)
            return

        if booking.status != BookingStatus.VALIDATED:
            logger.info(
                "release_payment_skipped",
                booking_id=booking_id,
                status=booking.status.value,
            )
            return

        try:
            if booking.stripe_payment_intent_id:
                await capture_payment_intent(booking.stripe_payment_intent_id)
        except Exception:
            logger.exception("release_payment_stripe_failed", booking_id=booking_id)
            return  # Don't update status if Stripe failed; will be retried by catch-all cron

        booking.status = BookingStatus.COMPLETED
        booking.payment_released_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info("payment_released", booking_id=booking_id)


async def release_overdue_payments() -> None:
    """Catch-all: find VALIDATED bookings past the release window and capture payments.

    This handles cases where the one-time scheduled job was lost (server restart).
    """
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.PAYMENT_RELEASE_DELAY_HOURS
        )
        result = await db.execute(
            select(Booking).where(
                Booking.status == BookingStatus.VALIDATED,
                Booking.updated_at < cutoff,
            )
        )
        bookings = result.scalars().all()

        for booking in bookings:
            try:
                if booking.stripe_payment_intent_id:
                    await capture_payment_intent(booking.stripe_payment_intent_id)
                booking.status = BookingStatus.COMPLETED
                booking.payment_released_at = datetime.now(timezone.utc)
                logger.info("overdue_payment_released", booking_id=str(booking.id))
            except Exception:
                logger.exception("overdue_payment_release_failed", booking_id=str(booking.id))

        await db.commit()


async def check_pending_acceptances() -> None:
    """Cancel bookings that haven't been accepted within the timeout period."""
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.MECHANIC_ACCEPTANCE_TIMEOUT_HOURS
        )
        result = await db.execute(
            select(Booking)
            .where(
                Booking.status == BookingStatus.PENDING_ACCEPTANCE,
                Booking.created_at < cutoff,
            )
            .options(
                selectinload(Booking.mechanic),
                selectinload(Booking.availability),
            )
        )
        bookings = result.scalars().all()

        for booking in bookings:
            try:
                if booking.stripe_payment_intent_id:
                    await cancel_payment_intent(booking.stripe_payment_intent_id)
            except Exception:
                logger.exception(
                    "pending_acceptance_cancel_stripe_failed",
                    booking_id=str(booking.id),
                )
                continue  # Skip this booking, try next

            booking.status = BookingStatus.CANCELLED
            booking.cancelled_at = datetime.now(timezone.utc)

            if booking.availability:
                booking.availability.is_booked = False

            logger.info(
                "pending_acceptance_expired",
                booking_id=str(booking.id),
                mechanic_id=str(booking.mechanic_id),
            )

        await db.commit()


async def send_reminders() -> None:
    """Send reminders for bookings happening in ~1 hour."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        window_start = now + timedelta(minutes=55)
        window_end = now + timedelta(minutes=65)

        # Filter by date at the database level for performance
        target_date = (now + timedelta(hours=1)).date()

        result = await db.execute(
            select(Booking)
            .where(Booking.status == BookingStatus.CONFIRMED)
            .join(Booking.availability)
            .where(Availability.date == target_date)
            .options(
                selectinload(Booking.buyer),
                selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
                selectinload(Booking.availability),
            )
        )
        bookings = result.scalars().all()

        for booking in bookings:
            if not booking.availability:
                continue
            slot_dt = datetime.combine(
                booking.availability.date,
                booking.availability.start_time,
                tzinfo=timezone.utc,
            )
            if window_start <= slot_dt <= window_end:
                # TODO: Send push notification / SMS
                logger.info(
                    "reminder_sent",
                    booking_id=str(booking.id),
                    buyer_phone=booking.buyer.phone if booking.buyer else None,
                    mechanic_phone=(
                        booking.mechanic.user.phone
                        if booking.mechanic and booking.mechanic.user
                        else None
                    ),
                )


def schedule_payment_release(booking_id: str) -> None:
    """Schedule a payment release job 2h from now."""
    run_time = datetime.now(timezone.utc) + timedelta(
        hours=settings.PAYMENT_RELEASE_DELAY_HOURS
    )
    scheduler.add_job(
        release_payment,
        "date",
        run_date=run_time,
        args=[booking_id],
        id=f"release_{booking_id}",
        replace_existing=True,
    )
    logger.info(
        "payment_release_scheduled",
        booking_id=booking_id,
        run_at=run_time.isoformat(),
    )


async def cleanup_old_webhook_events() -> None:
    """Delete processed webhook events older than 7 days."""
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=7)
        result = await db.execute(
            delete(ProcessedWebhookEvent).where(
                ProcessedWebhookEvent.processed_at < cutoff
            )
        )
        count = result.rowcount
        await db.commit()
        if count:
            logger.info("webhook_events_cleaned_up", deleted_count=count)


def start_scheduler() -> None:
    """Start the APScheduler with recurring cron jobs."""
    scheduler.add_job(
        check_pending_acceptances,
        "interval",
        minutes=5,
        id="check_pending_acceptances",
        replace_existing=True,
    )
    scheduler.add_job(
        send_reminders,
        "interval",
        minutes=15,
        id="send_reminders",
        replace_existing=True,
    )
    scheduler.add_job(
        release_overdue_payments,
        "interval",
        minutes=10,
        id="release_overdue_payments",
        replace_existing=True,
    )
    scheduler.add_job(
        cleanup_old_webhook_events,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_webhook_events",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler_started")
