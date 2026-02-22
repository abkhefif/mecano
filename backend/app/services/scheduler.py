# AUD-H05 / AUD-003: APScheduler job store configuration.
# When REDIS_URL is available, one-shot jobs (e.g. payment release) are persisted
# in Redis and survive server restarts.  The recurring cron job
# `release_overdue_payments` (runs every 10 minutes) still serves as a safety net.
# Without Redis the default MemoryJobStore is used (dev/test).

import asyncio
from datetime import datetime, timedelta, timezone

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import delete, select, update
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
from app.metrics import SCHEDULER_JOB_RUNS
from app.services.notifications import create_notification, send_booking_reminder
from app.services.penalties import apply_no_show_penalty, reset_no_show_if_eligible
from app.services.stripe_service import cancel_payment_intent, capture_payment_intent

logger = structlog.get_logger()

# AUD-003: Use RedisJobStore when Redis is available so that one-shot jobs
# (e.g. schedule_payment_release) survive worker/server restarts.
_jobstores: dict = {}
if settings.REDIS_URL:
    try:
        from urllib.parse import urlparse
        from apscheduler.jobstores.redis import RedisJobStore
        _parsed = urlparse(settings.REDIS_URL)
        # INFRA-10: Pass ssl=True when using rediss:// (TLS) to preserve encryption
        _redis_kwargs: dict = {
            "host": _parsed.hostname or "localhost",
            "port": _parsed.port or 6379,
            "db": int(_parsed.path.lstrip("/") or 0),
            "password": _parsed.password,
        }
        if _parsed.scheme == "rediss":
            _redis_kwargs["ssl"] = True
        _jobstores["default"] = RedisJobStore(**_redis_kwargs)
        logger.info("scheduler_using_redis_jobstore", redis_url="[redacted]")
    except Exception as exc:
        # Connection refused, missing package, etc. -- fall back to MemoryJobStore.
        logger.warning(
            "scheduler_redis_jobstore_failed",
            error=str(exc),
            fallback="MemoryJobStore",
        )

scheduler = AsyncIOScheduler(jobstores=_jobstores if _jobstores else {})


async def _acquire_scheduler_lock(job_name: str, ttl: int = 300) -> bool:
    """Try to acquire a distributed Redis lock for a scheduler job.

    Returns True if the lock was acquired (this worker should run the job).
    Returns False if another worker already holds the lock.
    Falls back to True (allow execution) if Redis is unavailable.
    """
    if not settings.REDIS_URL:
        return True
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        key = f"scheduler_lock:{job_name}"
        acquired = await r.set(key, "1", nx=True, ex=ttl)
        await r.aclose()
        return bool(acquired)
    except Exception:
        # Redis unavailable -- fall back to running the job (dev / single-worker mode)
        return True


async def release_payment(booking_id: str) -> None:
    """Capture the held payment and transfer to mechanic, 2h after validation.

    AUD4-006: Acquire the distributed lock BEFORE reading the booking to
    eliminate the TOCTOU race window between the status check and the lock.
    """
    # Acquire lock FIRST to prevent duplicate capture across workers
    if not await _acquire_scheduler_lock(f"release_payment_{booking_id}", ttl=600):
        logger.info("release_payment_lock_held", booking_id=booking_id)
        return

    async with async_session() as db:
        result = await db.execute(
            select(Booking).where(Booking.id == booking_id).with_for_update()
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
                await capture_payment_intent(
                    booking.stripe_payment_intent_id,
                    idempotency_key=f"release_{booking_id}",
                )
        except Exception as e:
            logger.exception("release_payment_stripe_failed", booking_id=booking_id, error_type=type(e).__name__)
            return  # Don't update status if Stripe failed; will be retried by catch-all cron

        booking.status = BookingStatus.COMPLETED
        booking.payment_released_at = datetime.now(timezone.utc)
        await db.commit()

        from app.metrics import BOOKINGS_COMPLETED, PAYMENTS_CAPTURED
        PAYMENTS_CAPTURED.inc()
        BOOKINGS_COMPLETED.inc()
        SCHEDULER_JOB_RUNS.labels(job_name="release_payment", status="success").inc()
        logger.info("payment_released", booking_id=booking_id)


SCHEDULER_BATCH_SIZE = 20


async def release_overdue_payments() -> None:
    """Catch-all: find VALIDATED bookings past the release window and capture payments.

    This handles cases where the one-time scheduled job was lost (server restart).
    Processes at most SCHEDULER_BATCH_SIZE bookings per run to bound memory usage;
    remaining bookings will be picked up in the next scheduled interval.
    """
    if not await _acquire_scheduler_lock("release_overdue_payments"):
        return
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.PAYMENT_RELEASE_DELAY_HOURS
        )
        result = await db.execute(
            select(Booking).where(
                Booking.status == BookingStatus.VALIDATED,
                Booking.updated_at < cutoff,
            ).with_for_update(skip_locked=True)
            .limit(SCHEDULER_BATCH_SIZE)
        )
        bookings = result.scalars().all()

        for booking in bookings:
            try:
                # I-002: Per-booking commit + rollback ensures each booking is
                # processed in isolation. If one booking fails (e.g. Stripe
                # error), the rollback resets the session state so subsequent
                # bookings can proceed without stale-session issues.
                if booking.stripe_payment_intent_id:
                    await capture_payment_intent(
                        booking.stripe_payment_intent_id,
                        idempotency_key=f"release_overdue_{booking.id}",
                    )
                booking.status = BookingStatus.COMPLETED
                booking.payment_released_at = datetime.now(timezone.utc)
                await db.commit()
                SCHEDULER_JOB_RUNS.labels(job_name="release_overdue_payments", status="success").inc()
                logger.info("overdue_payment_released", booking_id=str(booking.id))
            except Exception as e:
                await db.rollback()
                SCHEDULER_JOB_RUNS.labels(job_name="release_overdue_payments", status="error").inc()
                logger.exception(
                    "overdue_payment_release_failed",
                    booking_id=str(booking.id),
                    error_type=type(e).__name__,
                )


async def check_pending_acceptances() -> None:
    """Cancel bookings that haven't been accepted within the timeout period.

    Processes at most SCHEDULER_BATCH_SIZE bookings per run to bound memory usage.
    """
    if not await _acquire_scheduler_lock("check_pending_acceptances"):
        return
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
            .with_for_update(skip_locked=True)
            .limit(SCHEDULER_BATCH_SIZE)
        )
        bookings = result.scalars().all()

        for booking in bookings:
            try:
                # I-002: Per-booking commit + rollback ensures transactional
                # isolation. On failure, rollback resets the session state
                # so subsequent bookings are not affected by stale state.
                if booking.stripe_payment_intent_id:
                    # FIN-05: Idempotency key prevents duplicate Stripe cancellations on retries
                    await cancel_payment_intent(
                        booking.stripe_payment_intent_id,
                        idempotency_key=f"pending_expire_{booking.id}",
                    )

                booking.status = BookingStatus.CANCELLED
                booking.cancelled_at = datetime.now(timezone.utc)
                booking.cancelled_by = "mechanic"

                # R-01: Lock availability and only release if no other active booking references it
                if booking.availability_id:
                    avail_result = await db.execute(
                        select(Availability).where(Availability.id == booking.availability_id).with_for_update()
                    )
                    avail = avail_result.scalar_one_or_none()
                    if avail:
                        from sqlalchemy import func as sa_func
                        other_active = await db.execute(
                            select(sa_func.count(Booking.id)).where(
                                Booking.availability_id == booking.availability_id,
                                Booking.id != booking.id,
                                Booking.status != BookingStatus.CANCELLED,
                            )
                        )
                        if (other_active.scalar() or 0) == 0:
                            avail.is_booked = False

                await db.commit()
                SCHEDULER_JOB_RUNS.labels(job_name="check_pending_acceptances", status="success").inc()
                logger.info(
                    "pending_acceptance_expired",
                    booking_id=str(booking.id),
                    mechanic_id=str(booking.mechanic_id),
                )
            except Exception as e:
                await db.rollback()
                SCHEDULER_JOB_RUNS.labels(job_name="check_pending_acceptances", status="error").inc()
                logger.exception(
                    "pending_acceptance_cancel_failed",
                    booking_id=str(booking.id),
                    error_type=type(e).__name__,
                )


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

    # PERF-005: Filter at the SQL level on availability date to avoid loading
    # all confirmed bookings.  The window_start/window_end are datetimes, so we
    # extract the date range to narrow the query.  Fine-grained start_time
    # filtering is still done in Python because the slot datetime is
    # constructed from separate date + time columns.
    result = await db.execute(
        select(Booking)
        .where(
            Booking.status == BookingStatus.CONFIRMED,
            flag_col == False,  # noqa: E712
        )
        .join(Booking.availability)
        .where(
            Availability.date >= window_start.date(),
            Availability.date <= window_end.date(),
        )
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
                # I-001: Commit inside per-booking try block so a single failure
                # does not roll back the flag updates of previously processed bookings.
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.exception(
                    f"reminder_{hours_label}h_failed",
                    booking_id=str(booking.id),
                    error_type=type(e).__name__,
                )


async def send_reminders() -> None:
    """Send 24h and 2h reminders for confirmed bookings."""
    if not await _acquire_scheduler_lock("send_reminders"):
        return
    async with async_session() as db:
        now = datetime.now(timezone.utc)

        # --- 24h reminders ---
        try:
            await _send_window_reminders(
                db,
                window_start=now + timedelta(hours=23),
                window_end=now + timedelta(hours=25),
                hours_label=24,
                flag_field="reminder_24h_sent",
            )
        except Exception:
            await db.rollback()
            logger.exception("send_reminders_24h_failed")

        # --- 2h reminders ---
        try:
            await _send_window_reminders(
                db,
                window_start=now + timedelta(hours=1, minutes=45),
                window_end=now + timedelta(hours=2, minutes=15),
                hours_label=2,
                flag_field="reminder_2h_sent",
            )
        except Exception:
            await db.rollback()
            logger.exception("send_reminders_2h_failed")


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
    if not await _acquire_scheduler_lock("cleanup_old_webhook_events"):
        return
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
    """Send a weekly reminder to new/unverified mechanics who haven't uploaded identity documents.

    R-002: Targets mechanics where is_identity_verified is False (new unverified
    mechanics who need nudging), rather than active verified ones.
    """
    if not await _acquire_scheduler_lock("notify_unverified_mechanics"):
        return
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)

        # PERF-004: Use a subquery to filter out mechanics who already received
        # a notification in the last 7 days, avoiding N+1 queries.
        recent_notif_subq = (
            select(Notification.user_id)
            .where(
                Notification.type == NotificationType.PROFILE_VERIFICATION,
                Notification.created_at >= seven_days_ago,
            )
            .scalar_subquery()
        )

        result = await db.execute(
            select(MechanicProfile).where(
                MechanicProfile.identity_document_url.is_(None),
                MechanicProfile.is_identity_verified == False,  # noqa: E712  # R-002: target unverified mechanics
                MechanicProfile.user_id.notin_(recent_notif_subq),
            )
        )
        profiles = result.scalars().all()

        # L-06: Count actually notified mechanics separately from total found
        notified_count = 0
        for profile in profiles:
            await create_notification(
                db=db,
                user_id=profile.user_id,
                notification_type=NotificationType.PROFILE_VERIFICATION,
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
    if not await _acquire_scheduler_lock("cleanup_expired_blacklisted_tokens"):
        return
    async with async_session() as db:
        now = datetime.now(timezone.utc)
        result = await db.execute(
            delete(BlacklistedToken).where(BlacklistedToken.expires_at < now)
        )
        count = result.rowcount
        await db.commit()
        if count:
            logger.info("blacklisted_tokens_cleaned_up", deleted_count=count)


async def cleanup_old_notifications() -> None:
    """Delete read notifications older than 90 days."""
    if not await _acquire_scheduler_lock("cleanup_old_notifications"):
        return
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=90)
        result = await db.execute(
            delete(Notification).where(
                Notification.is_read == True,  # noqa: E712
                Notification.created_at < cutoff,
            )
        )
        count = result.rowcount
        await db.commit()
        if count:
            logger.info("old_notifications_cleaned_up", deleted_count=count)


async def cleanup_expired_push_tokens() -> None:
    """Clear push tokens that haven't been used in over 6 months."""
    if not await _acquire_scheduler_lock("cleanup_expired_push_tokens"):
        return
    async with async_session() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=180)
        # PERF-005: Bulk update instead of load-all-then-update pattern
        result = await db.execute(
            update(User)
            .where(
                User.expo_push_token.isnot(None),
                User.updated_at < cutoff,
            )
            .values(expo_push_token=None)
        )
        cleared_count = result.rowcount
        await db.commit()
        if cleared_count:
            logger.info("expired_push_tokens_cleared", cleared_count=cleared_count)


async def reset_no_show_weekly() -> None:
    """L-07: Weekly cron job to reset no-show counters for eligible mechanics."""
    if not await _acquire_scheduler_lock("reset_no_show_weekly"):
        return
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


def _extract_key_from_url(url: str | None) -> str | None:
    """Extract S3/R2 object key from a public or pre-signed URL.

    Strips the scheme + host and any query parameters (pre-signed tokens).

    Examples:
        "https://cdn.example.com/proofs/abc.jpg"       -> "proofs/abc.jpg"
        "https://r2.example.com/identity/x.pdf?X-Amz=…" -> "identity/x.pdf"
    """
    if not url:
        return None
    try:
        from urllib.parse import urlparse

        path = urlparse(url).path.lstrip("/")
        return path if path else None
    except Exception:
        return None


def _list_r2_keys_sync() -> set[str]:
    """List every object key in the R2 bucket (synchronous, paginated).

    SCHED-03: Extracted to sync function so it can run via asyncio.to_thread
    without blocking the event loop.
    """
    from app.services.storage import get_s3_client

    client = get_s3_client()
    keys: set[str] = set()
    paginator = client.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=settings.R2_BUCKET_NAME):
        for obj in page.get("Contents", []):
            keys.add(obj["Key"])
    return keys


async def _list_r2_keys() -> set[str]:
    """List every object key in the R2 bucket (async wrapper).

    Returns an empty set if R2 is not configured or on error.
    """
    if not settings.R2_ENDPOINT_URL:
        logger.info("orphaned_files_r2_not_configured")
        return set()

    try:
        keys = await asyncio.to_thread(_list_r2_keys_sync)
    except Exception:
        logger.exception("orphaned_files_r2_list_failed")
        return set()

    logger.info("orphaned_files_r2_listed", count=len(keys))
    return keys


async def _collect_db_keys(db) -> set[str]:
    """Collect all file keys referenced across the database.

    Scans: MechanicProfile (4 URL cols), ValidationProof (2 URL cols + JSON),
    Diploma (document_url), DisputeCase (photo_urls JSON), Report (pdf_url).
    """
    from app.models.diploma import Diploma
    from app.models.dispute import DisputeCase
    from app.models.report import Report
    from app.models.validation_proof import ValidationProof

    keys: set[str] = set()

    def _add(url: str | None) -> None:
        k = _extract_key_from_url(url)
        if k:
            keys.add(k)

    # 1. MechanicProfile documents
    rows = await db.execute(
        select(
            MechanicProfile.identity_document_url,
            MechanicProfile.selfie_with_id_url,
            MechanicProfile.cv_url,
            MechanicProfile.photo_url,
        )
    )
    for row in rows:
        for url in row:
            _add(url)

    # 2. ValidationProof photos
    rows = await db.execute(
        select(
            ValidationProof.photo_plate_url,
            ValidationProof.photo_odometer_url,
            ValidationProof.additional_photo_urls,
        )
    )
    for plate, odo, additional in rows:
        _add(plate)
        _add(odo)
        if additional and isinstance(additional, list):
            for url in additional:
                _add(url)

    # 3. Diplomas
    rows = await db.execute(select(Diploma.document_url))
    for (url,) in rows:
        _add(url)

    # 4. DisputeCase photos
    rows = await db.execute(select(DisputeCase.photo_urls))
    for (urls,) in rows:
        if urls and isinstance(urls, list):
            for url in urls:
                _add(url)

    # 5. Reports
    rows = await db.execute(select(Report.pdf_url))
    for (url,) in rows:
        _add(url)

    logger.info("orphaned_files_db_collected", count=len(keys))
    return keys


_ORPHAN_GRACE_DAYS = 7


async def detect_orphaned_files() -> None:
    """Detect and delete orphaned files in R2 after a 7-day grace period.

    Process:
      1. List all objects in the R2 bucket.
      2. Collect every file URL referenced in the database.
      3. Compute orphans = R2 keys - DB keys.
      4. For each orphan older than 7 days, delete it.

    The grace period prevents deleting files from in-progress uploads.
    Complies with RGPD Article 17 (right to erasure).
    """
    if not await _acquire_scheduler_lock("detect_orphaned_files"):
        return

    r2_keys = await _list_r2_keys()
    if not r2_keys:
        return

    async with async_session() as db:
        db_keys = await _collect_db_keys(db)

    orphans = r2_keys - db_keys
    if not orphans:
        logger.info("orphaned_files_none_found", r2=len(r2_keys), db=len(db_keys))
        return

    logger.info("orphaned_files_detected", count=len(orphans), r2=len(r2_keys), db=len(db_keys))

    from app.services.storage import get_s3_client

    client = get_s3_client()
    now = datetime.now(timezone.utc)
    grace = timedelta(days=_ORPHAN_GRACE_DAYS)
    deleted = skipped = errors = 0

    for key in orphans:
        try:
            # SCHED-03: Run blocking boto3 calls via asyncio.to_thread
            head = await asyncio.to_thread(
                client.head_object, Bucket=settings.R2_BUCKET_NAME, Key=key
            )
            age = now - head["LastModified"]
            if age > grace:
                await asyncio.to_thread(
                    client.delete_object, Bucket=settings.R2_BUCKET_NAME, Key=key
                )
                deleted += 1
                logger.info("orphaned_file_deleted", key=key, age_days=age.days)
            else:
                skipped += 1
        except Exception:
            errors += 1
            logger.exception("orphaned_file_error", key=key)

    logger.info(
        "orphaned_files_done",
        total=len(orphans),
        deleted=deleted,
        skipped_grace=skipped,
        errors=errors,
    )


def start_scheduler() -> None:
    """Start the APScheduler with recurring cron jobs."""
    scheduler.add_job(
        check_pending_acceptances,
        "interval",
        minutes=5,
        id="check_pending_acceptances",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        send_reminders,
        "interval",
        minutes=15,
        id="send_reminders",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        release_overdue_payments,
        "interval",
        minutes=10,
        id="release_overdue_payments",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        cleanup_old_webhook_events,
        "cron",
        hour=3,
        minute=0,
        id="cleanup_webhook_events",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # F-017: 7h UTC = 8h-9h France (CET/CEST)
    scheduler.add_job(
        notify_unverified_mechanics,
        "cron",
        hour=7,
        minute=0,
        id="notify_unverified_mechanics",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # C-03: Daily cleanup of expired blacklisted tokens
    scheduler.add_job(
        cleanup_expired_blacklisted_tokens,
        "cron",
        hour=4,
        minute=0,
        id="cleanup_blacklisted_tokens",
        replace_existing=True,
        misfire_grace_time=3600,
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
        misfire_grace_time=3600,
    )
    # Data retention: clean up old read notifications (>90 days) daily at 3 AM
    scheduler.add_job(
        cleanup_old_notifications,
        "cron",
        hour=3,
        minute=30,
        id="cleanup_old_notifications",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # Data retention: clean up expired push tokens (>6 months unused) weekly
    scheduler.add_job(
        cleanup_expired_push_tokens,
        "cron",
        day_of_week="sun",
        hour=4,
        minute=0,
        id="cleanup_expired_push_tokens",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # AUD-M07: Weekly orphaned file detection (Sunday 3:00 AM)
    scheduler.add_job(
        detect_orphaned_files,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="detect_orphaned_files",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # FIX-13: Add job error listener for resilience/observability
    def _job_error_listener(event):
        if event.exception:
            logger.exception(
                "scheduler_job_failed",
                job_id=event.job_id,
                error=str(event.exception),
            )

    from apscheduler.events import EVENT_JOB_ERROR
    scheduler.add_listener(_job_error_listener, EVENT_JOB_ERROR)

    scheduler.start()
    logger.info("scheduler_started")
