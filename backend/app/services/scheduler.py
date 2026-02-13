from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import async_session
from app.models.availability import Availability
from app.models.blacklisted_token import BlacklistedToken
from app.models.booking import Booking
from app.models.enums import BookingStatus, NotificationType
from app.models.mechanic_profile import MechanicProfile
from app.models.notification import Notification
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from app.services.notifications import create_notification, send_booking_reminder
from app.services.penalties import apply_no_show_penalty, reset_no_show_if_eligible
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
        except Exception as e:
            logger.exception("release_payment_stripe_failed", booking_id=booking_id, error_type=type(e).__name__)
            return  # Don't update status if Stripe failed; will be retried by catch-all cron

        booking.status = BookingStatus.COMPLETED
        booking.payment_released_at = datetime.now(timezone.utc)
        await db.commit()

        logger.info("payment_released", booking_id=booking_id)


SCHEDULER_BATCH_SIZE = 100


async def release_overdue_payments() -> None:
    """Catch-all: find VALIDATED bookings past the release window and capture payments.

    This handles cases where the one-time scheduled job was lost (server restart).
    Processes at most SCHEDULER_BATCH_SIZE bookings per run to bound memory usage;
    remaining bookings will be picked up in the next scheduled interval.
    """
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.PAYMENT_RELEASE_DELAY_HOURS
        )
        result = await db.execute(
            select(Booking).where(
                Booking.status == BookingStatus.VALIDATED,
                Booking.updated_at < cutoff,
            ).limit(SCHEDULER_BATCH_SIZE)
        )
        bookings = result.scalars().all()

        for booking in bookings:
            try:
                if booking.stripe_payment_intent_id:
                    await capture_payment_intent(booking.stripe_payment_intent_id)
                booking.status = BookingStatus.COMPLETED
                booking.payment_released_at = datetime.now(timezone.utc)
                await db.commit()
                logger.info("overdue_payment_released", booking_id=str(booking.id))
            except Exception as e:
                await db.rollback()
                logger.exception(
                    "overdue_payment_release_failed",
                    booking_id=str(booking.id),
                    error_type=type(e).__name__,
                )


async def check_pending_acceptances() -> None:
    """Cancel bookings that haven't been accepted within the timeout period.

    Processes at most SCHEDULER_BATCH_SIZE bookings per run to bound memory usage.
    """
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
            .limit(SCHEDULER_BATCH_SIZE)
        )
        bookings = result.scalars().all()

        for booking in bookings:
            try:
                if booking.stripe_payment_intent_id:
                    await cancel_payment_intent(booking.stripe_payment_intent_id)
            except Exception as e:
                logger.exception(
                    "pending_acceptance_cancel_stripe_failed",
                    booking_id=str(booking.id),
                    error_type=type(e).__name__,
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


async def _send_window_reminders(
    db,
    window_start: datetime,
    window_end: datetime,
    hours_label: int,
    flag_field: str,
) -> None:
    """Send reminders for bookings whose slot falls within the given time window.

    Args:
        db: async database session.
        window_start: earliest slot datetime to include.
        window_end: latest slot datetime to include.
        hours_label: human-readable hours value (24 or 2) passed to the notification.
        flag_field: name of the boolean column to filter/update (e.g. "reminder_24h_sent").
    """
    flag_col = getattr(Booking, flag_field)

    result = await db.execute(
        select(Booking)
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            flag_col == False,  # noqa: E712
        )
        .join(Booking.availability)
        .options(
            selectinload(Booking.buyer),
            selectinload(Booking.mechanic).selectinload(MechanicProfile.user),
            selectinload(Booking.availability),
        )
        .limit(SCHEDULER_BATCH_SIZE)
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
            try:
                buyer = booking.buyer
                mechanic_user = booking.mechanic.user if booking.mechanic else None
                buyer_name = buyer.first_name or buyer.email.split("@")[0] if buyer else "Client"
                mechanic_name = mechanic_user.first_name or mechanic_user.email.split("@")[0] if mechanic_user else "Mecanicien"
                vehicle_info = f"{booking.vehicle_brand} {booking.vehicle_model} ({booking.vehicle_year})"

                await send_booking_reminder(
                    booking_id=str(booking.id),
                    buyer_email=buyer.email if buyer else "",
                    buyer_name=buyer_name,
                    mechanic_email=mechanic_user.email if mechanic_user else "",
                    mechanic_name=mechanic_name,
                    vehicle_info=vehicle_info,
                    meeting_address=booking.meeting_address,
                    slot_date=booking.availability.date.isoformat(),
                    slot_time=booking.availability.start_time.strftime("%H:%M"),
                    hours_before=hours_label,
                    buyer_phone=buyer.phone if buyer else None,
                    mechanic_phone=mechanic_user.phone if mechanic_user else None,
                )
                setattr(booking, flag_field, True)
            except Exception as e:
                logger.exception(
                    f"reminder_{hours_label}h_failed",
                    booking_id=str(booking.id),
                    error_type=type(e).__name__,
                )

    await db.commit()


async def send_reminders() -> None:
    """Send 24h and 2h reminders for confirmed bookings."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # --- 24h reminders ---
        await _send_window_reminders(
            db,
            window_start=now + timedelta(hours=23),
            window_end=now + timedelta(hours=25),
            hours_label=24,
            flag_field="reminder_24h_sent",
        )

        # --- 2h reminders ---
        await _send_window_reminders(
            db,
            window_start=now + timedelta(hours=1, minutes=45),
            window_end=now + timedelta(hours=2, minutes=15),
            hours_label=2,
            flag_field="reminder_2h_sent",
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


async def notify_unverified_mechanics() -> None:
    """Send a weekly reminder to active mechanics who haven't uploaded identity documents."""
    async with async_session() as db:
        # Find active mechanics without identity documents
        result = await db.execute(
            select(MechanicProfile).where(
                MechanicProfile.identity_document_url.is_(None),
                MechanicProfile.is_active == True,
            )
        )
        profiles = result.scalars().all()

        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # L-06: Count actually notified mechanics separately from total found
        notified_count = 0
        for profile in profiles:
            # Check if a profile_verification notification was already sent in the last 7 days
            notif_result = await db.execute(
                select(Notification).where(
                    Notification.user_id == profile.user_id,
                    Notification.type == NotificationType.PROFILE_VERIFICATION.value,
                    Notification.created_at >= seven_days_ago,
                )
            )
            if notif_result.scalar_one_or_none():
                continue

            await create_notification(
                db=db,
                user_id=profile.user_id,
                notification_type=NotificationType.PROFILE_VERIFICATION.value,
                title="Verifiez votre profil",
                body=(
                    "Verifiez votre profil pour gagner la confiance de vos clients "
                    "et etre mis en avant dans les resultats de recherche. "
                    "Ajoutez votre piece d'identite des maintenant !"
                ),
                data={"action": "verify_identity"},
            )
            notified_count += 1

        await db.commit()
        logger.info(
            "notify_unverified_mechanics_done",
            total_found=len(profiles),
            notified_count=notified_count,
        )


async def cleanup_expired_blacklisted_tokens() -> None:
    """C-03: Delete blacklisted tokens that have already expired (daily cleanup)."""
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(BlacklistedToken).where(BlacklistedToken.expires_at < now)
        )
        count = result.rowcount
        await db.commit()
        if count:
            logger.info("blacklisted_tokens_cleaned_up", deleted_count=count)


async def reset_no_show_weekly() -> None:
    """L-07: Weekly cron job to reset no-show counters for eligible mechanics."""
    async with async_session() as db:
        result = await db.execute(
            select(MechanicProfile).where(
                MechanicProfile.no_show_count > 0,
                MechanicProfile.last_no_show_at.isnot(None),
            )
        )
        profiles = result.scalars().all()
        reset_count = 0
        for profile in profiles:
            old_count = profile.no_show_count
            await reset_no_show_if_eligible(db, profile)
            if profile.no_show_count != old_count:
                reset_count += 1
        await db.commit()
        if reset_count:
            logger.info("no_show_weekly_reset_done", reset_count=reset_count)


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
    scheduler.add_job(
        notify_unverified_mechanics,
        "cron",
        hour=9,
        minute=0,
        id="notify_unverified_mechanics",
        replace_existing=True,
    )
    # C-03: Daily cleanup of expired blacklisted tokens
    scheduler.add_job(
        cleanup_expired_blacklisted_tokens,
        "cron",
        hour=4,
        minute=0,
        id="cleanup_blacklisted_tokens",
        replace_existing=True,
    )
    # L-07: Weekly reset of no-show counters for eligible mechanics
    scheduler.add_job(
        reset_no_show_weekly,
        "cron",
        day_of_week="mon",
        hour=5,
        minute=0,
        id="reset_no_show_weekly",
        replace_existing=True,
    )
    scheduler.start()
    logger.info("scheduler_started")
