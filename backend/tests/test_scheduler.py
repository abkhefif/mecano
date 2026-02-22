import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.availability import Availability
from app.models.booking import Booking
from app.models.enums import BookingStatus, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from tests.conftest import engine, TestSessionFactory
from app.database import Base


def _make_booking(buyer_id, mechanic_id, avail_id=None, status=BookingStatus.VALIDATED,
                  stripe_pi="pi_mock_5000", created_at=None, updated_at=None):
    b = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_id,
        mechanic_id=mechanic_id,
        availability_id=avail_id,
        status=status,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Test",
        vehicle_model="Car",
        vehicle_year=2020,
        meeting_address="Toulouse",
        meeting_lat=43.61,
        meeting_lng=1.45,
        distance_km=5.0,
        base_price=Decimal("50.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("50.00"),
        commission_rate=Decimal("0.20"),
        commission_amount=Decimal("10.00"),
        mechanic_payout=Decimal("40.00"),
        stripe_payment_intent_id=stripe_pi,
    )
    if created_at:
        b.created_at = created_at
    if updated_at:
        b.updated_at = updated_at
    return b


@pytest.mark.asyncio
async def test_release_payment_success():
    """release_payment captures payment and marks booking as completed."""
    from app.services.scheduler import release_payment

    booking_id = uuid.uuid4()
    mock_booking = MagicMock()
    mock_booking.status = BookingStatus.VALIDATED
    mock_booking.stripe_payment_intent_id = "pi_mock_5000"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_booking

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.capture_payment_intent", new_callable=AsyncMock) as mock_capture:
        await release_payment(str(booking_id))
        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert call_args[0][0] == "pi_mock_5000"
        assert "idempotency_key" in call_args[1]
        assert mock_booking.status == BookingStatus.COMPLETED
        assert mock_booking.payment_released_at is not None


@pytest.mark.asyncio
async def test_release_payment_booking_not_found():
    """release_payment handles missing booking gracefully."""
    from app.services.scheduler import release_payment

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx):
        # Should not raise
        await release_payment(str(uuid.uuid4()))


@pytest.mark.asyncio
async def test_release_payment_wrong_status():
    """release_payment skips booking not in VALIDATED status."""
    from app.services.scheduler import release_payment

    mock_booking = MagicMock()
    mock_booking.status = BookingStatus.COMPLETED

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_booking

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.capture_payment_intent", new_callable=AsyncMock) as mock_capture:
        await release_payment(str(uuid.uuid4()))
        mock_capture.assert_not_called()


@pytest.mark.asyncio
async def test_release_payment_stripe_failure():
    """release_payment handles Stripe capture failure gracefully."""
    from app.services.scheduler import release_payment

    mock_booking = MagicMock()
    mock_booking.status = BookingStatus.VALIDATED
    mock_booking.stripe_payment_intent_id = "pi_test_fail"

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_booking

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.capture_payment_intent", new_callable=AsyncMock, side_effect=Exception("Stripe error")):
        # Should not raise
        await release_payment(str(uuid.uuid4()))
        # Status should remain VALIDATED since capture failed
        assert mock_booking.status == BookingStatus.VALIDATED


@pytest.mark.asyncio
async def test_release_overdue_payments():
    """release_overdue_payments finds and captures overdue validated bookings."""
    from app.services.scheduler import release_overdue_payments

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.VALIDATED
    mock_booking.stripe_payment_intent_id = "pi_mock_overdue"

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_booking]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.capture_payment_intent", new_callable=AsyncMock) as mock_capture, \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await release_overdue_payments()
        mock_capture.assert_called_once()
        call_args = mock_capture.call_args
        assert call_args[0][0] == "pi_mock_overdue"
        assert "idempotency_key" in call_args[1]
        assert mock_booking.status == BookingStatus.COMPLETED


@pytest.mark.asyncio
async def test_release_overdue_payments_stripe_failure():
    """release_overdue_payments handles per-booking Stripe failure."""
    from app.services.scheduler import release_overdue_payments

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.VALIDATED
    mock_booking.stripe_payment_intent_id = "pi_mock_fail"

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_booking]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.rollback = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.capture_payment_intent", new_callable=AsyncMock, side_effect=Exception("fail")), \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        # Should not raise
        await release_overdue_payments()
        mock_db.rollback.assert_called()


@pytest.mark.asyncio
async def test_check_pending_acceptances():
    """check_pending_acceptances cancels expired pending bookings."""
    from app.services.scheduler import check_pending_acceptances

    mock_avail = MagicMock()
    mock_avail.is_booked = True

    booking_id = uuid.uuid4()
    avail_id = uuid.uuid4()
    mock_booking = MagicMock()
    mock_booking.id = booking_id
    mock_booking.status = BookingStatus.PENDING_ACCEPTANCE
    mock_booking.stripe_payment_intent_id = "pi_mock_pending"
    mock_booking.mechanic_id = uuid.uuid4()
    mock_booking.availability = mock_avail
    mock_booking.availability_id = avail_id

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_booking]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    # Second execute call returns the locked availability row
    mock_avail_result = MagicMock()
    mock_avail_result.scalar_one_or_none.return_value = mock_avail

    # R-01: Third execute call returns count of other active bookings (0 = safe to release)
    mock_count_result = MagicMock()
    mock_count_result.scalar.return_value = 0

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(side_effect=[mock_result, mock_avail_result, mock_count_result])
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.cancel_payment_intent", new_callable=AsyncMock) as mock_cancel, \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await check_pending_acceptances()
        # FIN-05: Now called with idempotency key
        mock_cancel.assert_called_once_with(
            "pi_mock_pending",
            idempotency_key=f"pending_expire_{booking_id}",
        )
        assert mock_booking.status == BookingStatus.CANCELLED
        assert mock_avail.is_booked is False


@pytest.mark.asyncio
async def test_check_pending_acceptances_stripe_failure():
    """check_pending_acceptances skips bookings when Stripe cancel fails."""
    from app.services.scheduler import check_pending_acceptances

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.PENDING_ACCEPTANCE
    mock_booking.stripe_payment_intent_id = "pi_fail"
    mock_booking.mechanic_id = uuid.uuid4()
    mock_booking.availability = None

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_booking]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.cancel_payment_intent", new_callable=AsyncMock, side_effect=Exception("fail")), \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await check_pending_acceptances()
        # Status should NOT be changed since Stripe cancel failed
        assert mock_booking.status == BookingStatus.PENDING_ACCEPTANCE


@pytest.mark.asyncio
async def test_send_reminders_24h():
    """send_reminders sends 24h reminders for confirmed bookings in the window."""
    from app.services.scheduler import send_reminders

    now = datetime.now(timezone.utc)
    slot_time = now + timedelta(hours=24)

    mock_avail = MagicMock()
    mock_avail.date = slot_time.date()
    mock_avail.start_time = slot_time.time()

    mock_buyer = MagicMock()
    mock_buyer.email = "buyer@test.com"
    mock_buyer.first_name = "Jean"
    mock_buyer.phone = "+33600000001"

    mock_mech_user = MagicMock()
    mock_mech_user.email = "mech@test.com"
    mock_mech_user.first_name = "Pierre"
    mock_mech_user.phone = "+33600000002"

    mock_mechanic_profile = MagicMock()
    mock_mechanic_profile.user = mock_mech_user

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.CONFIRMED
    mock_booking.reminder_24h_sent = False
    mock_booking.availability = mock_avail
    mock_booking.buyer = mock_buyer
    mock_booking.mechanic = mock_mechanic_profile
    mock_booking.vehicle_brand = "Peugeot"
    mock_booking.vehicle_model = "308"
    mock_booking.vehicle_year = 2019
    mock_booking.meeting_address = "123 Rue Test"

    # Mock for 24h query
    mock_scalars_24h = MagicMock()
    mock_scalars_24h.all.return_value = [mock_booking]
    mock_result_24h = MagicMock()
    mock_result_24h.scalars.return_value = mock_scalars_24h

    # Mock for 2h query (empty)
    mock_scalars_2h = MagicMock()
    mock_scalars_2h.all.return_value = []
    mock_result_2h = MagicMock()
    mock_result_2h.scalars.return_value = mock_scalars_2h

    call_count = [0]

    async def mock_execute(query):
        result = mock_result_24h if call_count[0] == 0 else mock_result_2h
        call_count[0] += 1
        return result

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.send_booking_reminder", new_callable=AsyncMock) as mock_reminder, \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await send_reminders()
        mock_reminder.assert_called_once()
        call_kwargs = mock_reminder.call_args.kwargs
        assert call_kwargs["hours_before"] == 24
        assert call_kwargs["buyer_email"] == "buyer@test.com"
        assert mock_booking.reminder_24h_sent is True


@pytest.mark.asyncio
async def test_send_reminders_2h():
    """send_reminders sends 2h reminders for confirmed bookings in the window."""
    from app.services.scheduler import send_reminders

    now = datetime.now(timezone.utc)
    slot_time = now + timedelta(hours=2)

    mock_avail = MagicMock()
    mock_avail.date = slot_time.date()
    mock_avail.start_time = slot_time.time()

    mock_buyer = MagicMock()
    mock_buyer.email = "buyer2@test.com"
    mock_buyer.first_name = None
    mock_buyer.phone = None

    mock_buyer_email = MagicMock()
    mock_buyer.email = "buyer2@test.com"

    mock_mech_user = MagicMock()
    mock_mech_user.email = "mech2@test.com"
    mock_mech_user.first_name = None
    mock_mech_user.phone = None

    mock_mech_user_email = MagicMock()
    mock_mech_user.email = "mech2@test.com"

    mock_mechanic_profile = MagicMock()
    mock_mechanic_profile.user = mock_mech_user

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.CONFIRMED
    mock_booking.reminder_2h_sent = False
    mock_booking.availability = mock_avail
    mock_booking.buyer = mock_buyer
    mock_booking.mechanic = mock_mechanic_profile
    mock_booking.vehicle_brand = "Renault"
    mock_booking.vehicle_model = "Clio"
    mock_booking.vehicle_year = 2020
    mock_booking.meeting_address = "456 Rue Test"

    # Mock for 24h query (empty)
    mock_scalars_24h = MagicMock()
    mock_scalars_24h.all.return_value = []
    mock_result_24h = MagicMock()
    mock_result_24h.scalars.return_value = mock_scalars_24h

    # Mock for 2h query
    mock_scalars_2h = MagicMock()
    mock_scalars_2h.all.return_value = [mock_booking]
    mock_result_2h = MagicMock()
    mock_result_2h.scalars.return_value = mock_scalars_2h

    call_count = [0]

    async def mock_execute(query):
        result = mock_result_24h if call_count[0] == 0 else mock_result_2h
        call_count[0] += 1
        return result

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.send_booking_reminder", new_callable=AsyncMock) as mock_reminder, \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await send_reminders()
        mock_reminder.assert_called_once()
        call_kwargs = mock_reminder.call_args.kwargs
        assert call_kwargs["hours_before"] == 2
        assert mock_booking.reminder_2h_sent is True


@pytest.mark.asyncio
async def test_schedule_payment_release():
    """schedule_payment_release schedules a job with APScheduler."""
    from app.services.scheduler import schedule_payment_release

    with patch("app.services.scheduler.scheduler") as mock_scheduler:
        schedule_payment_release("booking-123")
        mock_scheduler.add_job.assert_called_once()
        call_kwargs = mock_scheduler.add_job.call_args
        assert call_kwargs[1]["id"] == "release_booking-123"


@pytest.mark.asyncio
async def test_cleanup_old_webhook_events():
    """cleanup_old_webhook_events deletes old processed events."""
    from app.services.scheduler import cleanup_old_webhook_events

    mock_result = MagicMock()
    mock_result.rowcount = 5

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await cleanup_old_webhook_events()
        mock_db.execute.assert_called_once()
        mock_db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_cleanup_old_webhook_events_none_deleted():
    """cleanup_old_webhook_events handles no events to delete."""
    from app.services.scheduler import cleanup_old_webhook_events

    mock_result = MagicMock()
    mock_result.rowcount = 0

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await cleanup_old_webhook_events()


@pytest.mark.asyncio
async def test_start_scheduler():
    """start_scheduler registers cron jobs and starts the scheduler."""
    from app.services.scheduler import start_scheduler

    with patch("app.services.scheduler.scheduler") as mock_scheduler:
        start_scheduler()
        # Should have 10 add_job calls (pending, reminders, overdue, cleanup,
        # notify_unverified, cleanup_blacklisted_tokens, reset_no_show_weekly,
        # cleanup_old_notifications, cleanup_expired_push_tokens,
        # detect_orphaned_files)
        assert mock_scheduler.add_job.call_count == 10
        mock_scheduler.start.assert_called_once()


@pytest.mark.asyncio
async def test_send_reminders_no_availability():
    """send_reminders skips bookings without availability."""
    from app.services.scheduler import send_reminders

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.availability = None

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_booking]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_scalars_empty = MagicMock()
    mock_scalars_empty.all.return_value = []
    mock_result_empty = MagicMock()
    mock_result_empty.scalars.return_value = mock_scalars_empty

    call_count = [0]

    async def mock_execute(query):
        result = mock_result if call_count[0] == 0 else mock_result_empty
        call_count[0] += 1
        return result

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.send_booking_reminder", new_callable=AsyncMock) as mock_reminder, \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        await send_reminders()
        mock_reminder.assert_not_called()


@pytest.mark.asyncio
async def test_send_reminders_exception_handled():
    """send_reminders handles exceptions per-booking without crashing."""
    from app.services.scheduler import send_reminders

    now = datetime.now(timezone.utc)
    slot_time = now + timedelta(hours=24)

    mock_avail = MagicMock()
    mock_avail.date = slot_time.date()
    mock_avail.start_time = slot_time.time()

    mock_buyer = MagicMock()
    mock_buyer.email = "buyer@fail.com"
    mock_buyer.first_name = "Fail"
    mock_buyer.phone = None

    mock_mech_user = MagicMock()
    mock_mech_user.email = "mech@fail.com"
    mock_mech_user.first_name = "Fail"
    mock_mech_user.phone = None

    mock_mechanic_profile = MagicMock()
    mock_mechanic_profile.user = mock_mech_user

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.availability = mock_avail
    mock_booking.buyer = mock_buyer
    mock_booking.mechanic = mock_mechanic_profile
    mock_booking.vehicle_brand = "Test"
    mock_booking.vehicle_model = "Fail"
    mock_booking.vehicle_year = 2020
    mock_booking.meeting_address = "Fail Address"
    mock_booking.reminder_24h_sent = False

    mock_scalars = MagicMock()
    mock_scalars.all.return_value = [mock_booking]
    mock_result = MagicMock()
    mock_result.scalars.return_value = mock_scalars

    mock_scalars_empty = MagicMock()
    mock_scalars_empty.all.return_value = []
    mock_result_empty = MagicMock()
    mock_result_empty.scalars.return_value = mock_scalars_empty

    call_count = [0]

    async def mock_execute(query):
        result = mock_result if call_count[0] == 0 else mock_result_empty
        call_count[0] += 1
        return result

    mock_db = AsyncMock()
    mock_db.execute = mock_execute
    mock_db.commit = AsyncMock()

    mock_session_ctx = AsyncMock()
    mock_session_ctx.__aenter__ = AsyncMock(return_value=mock_db)
    mock_session_ctx.__aexit__ = AsyncMock(return_value=False)

    with patch("app.services.scheduler.async_session", return_value=mock_session_ctx), \
         patch("app.services.scheduler.send_booking_reminder", new_callable=AsyncMock, side_effect=Exception("boom")), \
         patch("app.services.scheduler._acquire_scheduler_lock", new_callable=AsyncMock, return_value=True):
        # Should not raise
        await send_reminders()
        # reminder_24h_sent should NOT be True since sending failed
        assert mock_booking.reminder_24h_sent is False
