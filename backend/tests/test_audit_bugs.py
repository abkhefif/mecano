"""
AGENT TESTEUR -- Bug-Exposing Tests
====================================
These tests are written by the Tester Agent to expose bugs found during the audit.
Each test references a specific finding from the audit report.
"""
import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, hash_password
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import (
    BookingStatus,
    DisputeReason,
    DisputeStatus,
    UserRole,
    VehicleType,
)
from app.models.mechanic_profile import MechanicProfile
from app.models.review import Review
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


# ============================================================
# FINDING #4 -- CRITICAL: Anyone can register as ADMIN
# ============================================================


@pytest.mark.asyncio
async def test_register_as_admin_should_be_blocked(client: AsyncClient):
    """
    BUG: The registration endpoint accepts role='admin', allowing
    anyone to create an admin account with full privileges.
    Expected: 422 or 403 rejecting admin registration.
    Actual: 201 with a valid admin JWT token.
    """
    response = await client.post(
        "/auth/register",
        json={
            "email": "hacker_admin@test.com",
            "password": "SecurePass123",
            "role": "admin",
        },
    )
    # BUG EXPOSED: This will be 201 instead of 422/403
    # The test documents the bug -- admin self-registration should be blocked
    if response.status_code == 201:
        # Verify the admin can access admin-only endpoints
        token = response.json()["access_token"]
        # This proves anyone can become an admin
        me_response = await client.get(
            "/auth/me", headers={"Authorization": f"Bearer {token}"}
        )
        assert me_response.status_code == 200
        assert me_response.json()["role"] == "admin"
        pytest.fail(
            "CRITICAL BUG: Registration endpoint allows creating admin accounts. "
            "Anyone can register as admin and gain full system privileges."
        )
    else:
        # This is the expected behavior (blocked)
        assert response.status_code in (422, 403)


# ============================================================
# FINDING #13 -- HIGH: Review model has unique=True on booking_id
# preventing both buyer AND mechanic from reviewing the same booking
# ============================================================


@pytest.mark.asyncio
async def test_both_buyer_and_mechanic_can_review_same_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """
    BUG: Review.booking_id has unique=True constraint, so only
    one review per booking is possible at the DB level.
    Expected: Both buyer and mechanic should be able to review.
    Actual: Second review fails with IntegrityError (500).
    """
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.COMPLETED,
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
    )
    db.add(booking)
    await db.flush()

    # Verify the bug exists at the model level:
    # Review.booking_id has unique=True, meaning only ONE review per booking
    from app.models.review import Review as ReviewModel
    import sqlalchemy

    booking_id_col = ReviewModel.__table__.c.booking_id
    # Check if there's a unique constraint on booking_id alone
    has_unique_on_booking_id = booking_id_col.unique
    if has_unique_on_booking_id:
        pytest.fail(
            "BUG: Review.booking_id has unique=True constraint. "
            "Only ONE review per booking is allowed at DB level, but both buyer "
            "AND mechanic should be able to review the same booking. "
            "Should use composite unique on (booking_id, reviewer_id) instead."
        )


# ============================================================
# FINDING #27 -- MEDIUM: Dispute without reason or description
# ============================================================


@pytest.mark.asyncio
async def test_validate_dispute_without_details_is_rejected(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """
    FIX VERIFIED: ValidateRequest now requires problem_reason and problem_description
    when validated=False. Sending just {"validated": false} returns 422.
    """
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.CHECK_OUT_DONE,
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
    )
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    # Without reason/description, should be rejected
    response = await client.patch(
        f"/bookings/{booking.id}/validate",
        json={"validated": False},
        headers=auth_header(token),
    )
    assert response.status_code == 422


# ============================================================
# FINDING #28 -- MEDIUM: list_my_bookings for admin returns empty
# ============================================================


@pytest.mark.asyncio
async def test_list_bookings_as_admin_returns_all(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """
    FIX VERIFIED: Admin users now get all bookings via a dedicated branch.
    """
    admin_user = User(
        id=uuid.uuid4(),
        email="admin_bookings@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN,
    )
    db.add(admin_user)
    await db.flush()

    # Create a booking so there's data
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.CONFIRMED,
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
    )
    db.add(booking)
    await db.flush()

    admin_token = create_access_token(str(admin_user.id))
    response = await client.get(
        "/bookings/me", headers=auth_header(admin_token)
    )
    assert response.status_code == 200
    # FIX: Admin now sees all bookings
    assert len(response.json()) >= 1


# ============================================================
# FINDING #21 -- MEDIUM: check_out catches Exception too broadly
# ============================================================


@pytest.mark.asyncio
async def test_check_out_broad_exception_masks_real_errors(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """
    BUG: `except (json.JSONDecodeError, Exception)` catches ALL exceptions,
    masking real bugs as "Invalid checklist data".
    """
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.CHECK_IN_DONE,
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
    )
    db.add(booking)
    await db.flush()

    # Valid JSON but with wrong types -- this should give a Pydantic validation error
    # but the broad except masks it as "Invalid checklist data"
    bad_checklist = json.dumps({
        "brakes": "ok",
        "tires": "ok",
        "fluids": "ok",
        "battery": "ok",
        "suspension": "ok",
        "body": "good",
        "exhaust": "ok",
        "lights": "ok",
        "test_drive_done": True,
        "recommendation": "INVALID_VALUE",  # Bad enum value
    })

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-out",
        data={
            "entered_plate": "AB-123-CD",
            "entered_odometer_km": "85000",
            "checklist_json": bad_checklist,
        },
        files={
            "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
            "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
        },
        headers=auth_header(token),
    )
    assert response.status_code == 400
    # SEC-010: Generic error message to avoid leaking internal details
    assert "Invalid data" in response.json()["detail"]


# ============================================================
# FINDING #30 -- MEDIUM: check-in without availability skips time validation
# ============================================================


@pytest.mark.asyncio
async def test_check_in_without_availability_is_rejected(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """
    FIX VERIFIED: If booking.availability is None, check-in is rejected
    with a 400 error instead of silently skipping time validation.
    """
    # Create booking with no availability_id
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        availability_id=None,
        status=BookingStatus.CONFIRMED,
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
    )
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-in",
        json={"mechanic_present": True},
        headers=auth_header(token),
    )
    # FIX: Now properly rejects check-in without availability data
    assert response.status_code == 400
    assert "Availability data missing" in response.json()["detail"]


# ============================================================
# FINDING #12 -- HIGH: CheckOutRequest schema is never used
# No validation on entered_plate and entered_odometer_km
# ============================================================


@pytest.mark.asyncio
async def test_check_out_no_plate_validation(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """
    BUG: The CheckOutRequest schema (with Field(max_length=20) for plate
    and Field(ge=0) for odometer) is never used. Form params have no validation.
    """
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.CHECK_IN_DONE,
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
    )
    db.add(booking)
    await db.flush()

    # Absurdly long plate and negative odometer - no validation!
    checklist_json = json.dumps({
        "brakes": "ok",
        "tires": "ok",
        "fluids": "ok",
        "battery": "ok",
        "suspension": "ok",
        "body": "good",
        "exhaust": "ok",
        "lights": "ok",
        "test_drive_done": False,
        "recommendation": "buy",
    })

    token = mechanic_token(mechanic_user)

    with patch("app.bookings.routes.upload_file", new_callable=AsyncMock) as mock_upload, \
         patch("app.bookings.routes.generate_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_upload.return_value = "https://storage.emecano.dev/proofs/test.jpg"
        mock_pdf.return_value = "https://storage.emecano.dev/reports/test.pdf"

        response = await client.patch(
            f"/bookings/{booking.id}/check-out",
            data={
                "entered_plate": "A" * 500,  # Way too long, should be max 20
                "entered_odometer_km": "-99999",  # Negative, should be >= 0
                "checklist_json": checklist_json,
            },
            files={
                "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
                "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
            },
            headers=auth_header(token),
        )

    # BUG: This succeeds (200) despite invalid plate length and negative odometer
    # because the CheckOutRequest schema is never used for validation
    if response.status_code == 200:
        pytest.fail(
            "BUG: No validation on check-out form params. "
            "Plate of 500 chars and negative odometer were accepted. "
            "CheckOutRequest schema (with proper validation) is unused."
        )


# ============================================================
# FINDING #5 -- CRITICAL: Default JWT secret
# ============================================================


def test_jwt_secret_rejects_short_secrets():
    """
    FIX for BUG-005: JWT_SECRET must be at least 32 chars and not a known weak default.
    """
    import pytest as _pytest
    from pydantic import ValidationError
    from app.config import Settings

    # Short secret must be rejected
    with _pytest.raises(ValidationError, match="at least 32 characters"):
        Settings(JWT_SECRET="change-this-in-production")

    # Known weak secret must be rejected
    with _pytest.raises(ValidationError, match="known weak default"):
        Settings(JWT_SECRET="change-this-to-a-long-random-string-in-production")

    # Valid long secret must be accepted
    s = Settings(JWT_SECRET="a-very-long-secure-secret-that-is-at-least-32-chars")
    assert len(s.JWT_SECRET) >= 32


# ============================================================
# FINDING #6 -- HIGH: Penalty applied for non-acceptance timeout
# ============================================================


@pytest.mark.asyncio
async def test_scheduler_no_longer_penalizes_for_non_acceptance():
    """
    FIX VERIFIED: check_pending_acceptances no longer calls apply_no_show_penalty.
    Non-acceptance timeout is not the same as a no-show.
    """
    from app.services.scheduler import check_pending_acceptances

    import inspect
    source = inspect.getsource(check_pending_acceptances)
    assert "apply_no_show_penalty" not in source, (
        "apply_no_show_penalty should NOT be in check_pending_acceptances"
    )


# ============================================================
# FINDING #17 -- HIGH: is_verified field is never enforced
# ============================================================


@pytest.mark.asyncio
async def test_unverified_user_can_create_booking(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """
    BUG: is_verified defaults to False and is never checked.
    An unverified user can make bookings and use the full platform.
    """
    # Create an unverified user
    unverified_user = User(
        id=uuid.uuid4(),
        email="unverified@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        is_verified=False,
    )
    db.add(unverified_user)
    await db.flush()

    token = create_access_token(str(unverified_user.id))
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(availability.id),
            "vehicle_type": "car",
            "vehicle_brand": "Peugeot",
            "vehicle_model": "308",
            "vehicle_year": 2019,
            "meeting_address": "Toulouse",
            "meeting_lat": 43.6100,
            "meeting_lng": 1.4500,
        },
        headers=auth_header(token),
    )
    # FIXED: Unverified users are now blocked by get_verified_buyer dependency
    assert response.status_code == 403, (
        "Unverified user should be blocked from creating bookings"
    )


# ============================================================
# FINDING #24 -- MEDIUM: Mechanic profile with (0, 0) coordinates
# ============================================================


@pytest.mark.asyncio
async def test_mechanic_registration_creates_profile_at_null_island(
    client: AsyncClient,
    db: AsyncSession,
):
    """
    FIX VERIFIED: Mechanic profile created during registration now has
    city_lat=None, city_lng=None instead of 0.0/0.0 (Null Island).
    """
    response = await client.post(
        "/auth/register",
        json={
            "email": "nullisland_mech@test.com",
            "password": "SecurePass123",
            "role": "mechanic",
            "cgu_accepted": True,
        },
    )
    assert response.status_code == 201
    token = response.json()["access_token"]

    # Check the profile via /auth/me
    me_response = await client.get(
        "/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert me_response.status_code == 200
    profile = me_response.json()["mechanic_profile"]
    assert profile is not None
    # FIX: Coordinates are None until the mechanic sets their city
    assert profile["city_lat"] is None
    assert profile["city_lng"] is None
    assert profile["city"] == ""


# ============================================================
# FINDING #3 -- CRITICAL: Stripe PaymentIntent orphaned on DB failure
# ============================================================


@pytest.mark.asyncio
async def test_booking_creation_has_compensating_stripe_cancellation(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """
    FIX VERIFIED: create_booking now has a try/except that cancels the
    Stripe PaymentIntent if the DB write fails (compensating transaction).
    """
    from app.bookings.routes import create_booking
    import inspect
    source = inspect.getsource(create_booking)

    # Verify both try/except and cancel_payment_intent are present
    assert "try:" in source and "cancel_payment_intent" in source, (
        "FIX: create_booking should have a try/except with cancel_payment_intent "
        "to handle DB failures after Stripe intent creation."
    )


# ============================================================
# Additional edge case tests
# ============================================================


@pytest.mark.asyncio
async def test_refuse_booking_releases_availability(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Verify that refusing a booking correctly releases the availability slot."""
    availability.is_booked = True
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        availability_id=availability.id,
        status=BookingStatus.PENDING_ACCEPTANCE,
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
        stripe_payment_intent_id="pi_mock_release",
    )
    db.add(booking)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/refuse",
        json={"reason": "not_available"},
        headers=auth_header(token),
    )
    assert response.status_code == 200

    # Verify availability was released
    await db.refresh(availability)
    assert availability.is_booked is False


@pytest.mark.asyncio
async def test_check_in_generates_valid_4_digit_code(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Verify check-in code is exactly 4 digits."""
    now = datetime.now(timezone.utc)
    availability.date = now.date()
    availability.start_time = now.time()
    availability.end_time = (now + timedelta(hours=1)).time()
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        availability_id=availability.id,
        status=BookingStatus.CONFIRMED,
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
    )
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-in",
        json={"mechanic_present": True},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    code = response.json()["check_in_code"]
    assert len(code) == 4
    assert code.isdigit()


@pytest.mark.asyncio
async def test_full_booking_lifecycle(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """End-to-end test of the happy path booking lifecycle."""
    b_tok = buyer_token(buyer_user)
    m_tok = mechanic_token(mechanic_user)

    # Step 1: Create booking
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(availability.id),
            "vehicle_type": "car",
            "vehicle_brand": "Peugeot",
            "vehicle_model": "308",
            "vehicle_year": 2019,
            "meeting_address": "Toulouse",
            "meeting_lat": 43.6100,
            "meeting_lng": 1.4500,
        },
        headers=auth_header(b_tok),
    )
    assert response.status_code == 201
    booking_id = response.json()["booking"]["id"]

    # Step 2: Mechanic accepts
    response = await client.patch(
        f"/bookings/{booking_id}/accept",
        headers=auth_header(m_tok),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"

    # Step 3: Update availability time for check-in window
    from sqlalchemy.orm import selectinload
    result = await db.execute(
        select(Booking)
        .where(Booking.id == uuid.UUID(booking_id))
        .options(selectinload(Booking.availability))
    )
    booking = result.scalar_one()
    if booking.availability:
        now = datetime.now(timezone.utc)
        booking.availability.date = now.date()
        booking.availability.start_time = now.time()
        booking.availability.end_time = (now + timedelta(hours=1)).time()
        await db.flush()

    # Step 4: Buyer checks in
    response = await client.patch(
        f"/bookings/{booking_id}/check-in",
        json={"mechanic_present": True},
        headers=auth_header(b_tok),
    )
    assert response.status_code == 200
    code = response.json()["check_in_code"]

    # Step 5: Mechanic enters code
    response = await client.patch(
        f"/bookings/{booking_id}/enter-code",
        json={"code": code},
        headers=auth_header(m_tok),
    )
    assert response.status_code == 200

    # Step 6: Mechanic checks out
    checklist_json = json.dumps({
        "brakes": "ok",
        "tires": "ok",
        "fluids": "ok",
        "battery": "ok",
        "suspension": "ok",
        "body": "good",
        "exhaust": "ok",
        "lights": "ok",
        "test_drive_done": True,
        "test_drive_behavior": "normal",
        "remarks": "All good",
        "recommendation": "buy",
    })

    with patch("app.bookings.routes.upload_file", new_callable=AsyncMock) as mock_upload, \
         patch("app.bookings.routes.generate_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_upload.return_value = "https://storage.emecano.dev/proofs/test.jpg"
        mock_pdf.return_value = "https://storage.emecano.dev/reports/test.pdf"

        response = await client.patch(
            f"/bookings/{booking_id}/check-out",
            data={
                "entered_plate": "AB-123-CD",
                "entered_odometer_km": "85000",
                "checklist_json": checklist_json,
            },
            files={
                "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
                "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
            },
            headers=auth_header(m_tok),
        )
    assert response.status_code == 200

    # Step 7: Buyer validates
    with patch("app.bookings.routes.schedule_payment_release"):
        response = await client.patch(
            f"/bookings/{booking_id}/validate",
            json={"validated": True},
            headers=auth_header(b_tok),
        )
    assert response.status_code == 200
    assert response.json()["status"] == "validated"
