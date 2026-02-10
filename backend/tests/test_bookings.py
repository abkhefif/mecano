import json
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.availability import Availability
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


@pytest.mark.asyncio
async def test_create_booking_success(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(availability.id),
            "vehicle_type": "car",
            "vehicle_brand": "Peugeot",
            "vehicle_model": "308",
            "vehicle_year": 2019,
            "meeting_address": "123 Rue Test, Toulouse",
            "meeting_lat": 43.6100,
            "meeting_lng": 1.4500,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["booking"]["status"] == "pending_acceptance"
    assert data["booking"]["vehicle_brand"] == "Peugeot"
    assert float(data["booking"]["base_price"]) == 50.0


@pytest.mark.asyncio
async def test_create_booking_slot_already_booked(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    availability.is_booked = True
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(availability.id),
            "vehicle_type": "car",
            "vehicle_brand": "Renault",
            "vehicle_model": "Clio",
            "vehicle_year": 2020,
            "meeting_address": "456 Rue Test, Toulouse",
            "meeting_lat": 43.6100,
            "meeting_lng": 1.4500,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_create_booking_too_close_in_time(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    # Create an availability slot for 30 min from now (too close)
    now = datetime.now(timezone.utc)
    avail = Availability(
        id=uuid.uuid4(),
        mechanic_id=mechanic_profile.id,
        date=now.date(),
        start_time=(now + timedelta(minutes=30)).time(),
        end_time=(now + timedelta(minutes=90)).time(),
        is_booked=False,
    )
    db.add(avail)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(avail.id),
            "vehicle_type": "car",
            "vehicle_brand": "Citroen",
            "vehicle_model": "C3",
            "vehicle_year": 2018,
            "meeting_address": "Toulouse",
            "meeting_lat": 43.6100,
            "meeting_lng": 1.4500,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "2 hours" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_booking_wrong_vehicle_type(
    client: AsyncClient,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(availability.id),
            "vehicle_type": "utility",
            "vehicle_brand": "Fiat",
            "vehicle_model": "Ducato",
            "vehicle_year": 2017,
            "meeting_address": "Toulouse",
            "meeting_lat": 43.6100,
            "meeting_lng": 1.4500,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "vehicle type" in response.json()["detail"]


@pytest.mark.asyncio
async def test_accept_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    # Create a booking first
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        availability_id=availability.id,
        status=BookingStatus.PENDING_ACCEPTANCE,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Peugeot",
        vehicle_model="308",
        vehicle_year=2019,
        meeting_address="Toulouse",
        meeting_lat=43.6100,
        meeting_lng=1.4500,
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/accept",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "confirmed"


@pytest.mark.asyncio
async def test_refuse_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        availability_id=availability.id,
        status=BookingStatus.PENDING_ACCEPTANCE,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Renault",
        vehicle_model="Clio",
        vehicle_year=2020,
        meeting_address="Toulouse",
        meeting_lat=43.6100,
        meeting_lng=1.4500,
        distance_km=5.0,
        base_price=Decimal("50.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("50.00"),
        commission_rate=Decimal("0.20"),
        commission_amount=Decimal("10.00"),
        mechanic_payout=Decimal("40.00"),
        stripe_payment_intent_id="pi_mock_5000",
    )
    db.add(booking)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/refuse",
        json={"reason": "too_far"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_check_in_mechanic_present(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    # Set availability to current time window for check-in
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
    data = response.json()
    assert "check_in_code" in data
    assert len(data["check_in_code"]) == 4


@pytest.mark.asyncio
async def test_check_in_mechanic_absent(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
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
        json={"mechanic_present": False},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["dispute_opened"] is True


@pytest.mark.asyncio
async def test_enter_code_correct(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.AWAITING_MECHANIC_CODE,
        check_in_code="1234",
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/enter-code",
        json={"code": "1234"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "checked_in"


@pytest.mark.asyncio
async def test_enter_code_incorrect(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.AWAITING_MECHANIC_CODE,
        check_in_code="1234",
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/enter-code",
        json={"code": "9999"},
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "Incorrect" in response.json()["detail"]


@pytest.mark.asyncio
async def test_validate_booking_success(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
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
    with patch("app.bookings.routes.schedule_payment_release"):
        response = await client.patch(
            f"/bookings/{booking.id}/validate",
            json={"validated": True},
            headers=auth_header(token),
        )
    assert response.status_code == 200
    assert response.json()["status"] == "validated"


@pytest.mark.asyncio
async def test_validate_booking_dispute(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
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
    response = await client.patch(
        f"/bookings/{booking.id}/validate",
        json={
            "validated": False,
            "problem_reason": "wrong_info",
            "problem_description": "Wrong plate number in the report",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["dispute_opened"] is True


@pytest.mark.asyncio
async def test_list_my_bookings(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
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

    token = buyer_token(buyer_user)
    response = await client.get("/bookings/me", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vehicle_brand"] == "Test"


# ---- Additional tests for coverage ----


@pytest.mark.asyncio
async def test_create_booking_availability_not_found(
    client: AsyncClient,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test creating a booking with a non-existent availability."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(uuid.uuid4()),
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
    assert response.status_code == 404
    assert "Availability slot not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_booking_mechanic_not_found(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Test creating a booking with a non-existent mechanic ID."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(uuid.uuid4()),
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
    assert response.status_code == 404
    assert "Mechanic not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_booking_mechanic_not_verified(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Test creating a booking when the mechanic is not identity-verified."""
    mechanic_profile.is_identity_verified = False
    await db.flush()

    token = buyer_token(buyer_user)
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
    assert response.status_code == 400
    assert "not verified" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_booking_slot_wrong_mechanic(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Test creating a booking where the availability doesn't belong to the mechanic."""
    from app.auth.service import hash_password

    # Create a second mechanic
    other_user = User(
        id=uuid.uuid4(),
        email="other_mechanic@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000099",
    )
    db.add(other_user)
    await db.flush()

    other_profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=other_user.id,
        city="toulouse",
        city_lat=43.6047,
        city_lng=1.4442,
        max_radius_km=50,
        free_zone_km=10,
        accepted_vehicle_types=["car"],
        is_identity_verified=True,
        is_active=True,
    )
    db.add(other_profile)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(other_profile.id),
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
    assert response.status_code == 400
    assert "does not belong" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_booking_beyond_max_radius(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Test creating a booking where the meeting point is beyond max radius."""
    token = buyer_token(buyer_user)
    # Paris coords - far from Toulouse (mechanic_profile.max_radius_km=50)
    response = await client.post(
        "/bookings",
        json={
            "mechanic_id": str(mechanic_profile.id),
            "availability_id": str(availability.id),
            "vehicle_type": "car",
            "vehicle_brand": "Peugeot",
            "vehicle_model": "308",
            "vehicle_year": 2019,
            "meeting_address": "Paris",
            "meeting_lat": 48.8566,
            "meeting_lng": 2.3522,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "beyond" in response.json()["detail"].lower() or "km away" in response.json()["detail"]


@pytest.mark.asyncio
async def test_accept_booking_not_your_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test accepting a booking that belongs to a different mechanic."""
    from app.auth.service import hash_password

    # Create another mechanic user/profile
    other_mech_user = User(
        id=uuid.uuid4(),
        email="other_mech2@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000088",
    )
    db.add(other_mech_user)
    await db.flush()

    other_profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=other_mech_user.id,
        city="toulouse",
        city_lat=43.6047,
        city_lng=1.4442,
        max_radius_km=50,
        free_zone_km=10,
        accepted_vehicle_types=["car"],
        is_identity_verified=True,
        is_active=True,
    )
    db.add(other_profile)
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=other_profile.id,
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
    )
    db.add(booking)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/accept",
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "Not your booking" in response.json()["detail"]


@pytest.mark.asyncio
async def test_accept_booking_wrong_status(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test accepting a booking that is not in PENDING_ACCEPTANCE status."""
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/accept",
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_accept_booking_not_found(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test accepting a non-existent booking."""
    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{uuid.uuid4()}/accept",
        headers=auth_header(token),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_refuse_booking_not_your_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test refusing a booking that belongs to a different mechanic."""
    from app.auth.service import hash_password

    other_mech_user = User(
        id=uuid.uuid4(),
        email="other_mech3@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000077",
    )
    db.add(other_mech_user)
    await db.flush()

    other_profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=other_mech_user.id,
        city="toulouse",
        city_lat=43.6047,
        city_lng=1.4442,
        max_radius_km=50,
        free_zone_km=10,
        accepted_vehicle_types=["car"],
        is_identity_verified=True,
        is_active=True,
    )
    db.add(other_profile)
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=other_profile.id,
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
    )
    db.add(booking)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/refuse",
        json={"reason": "too_far"},
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_refuse_booking_wrong_status(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test refusing a booking that is not in PENDING_ACCEPTANCE status."""
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/refuse",
        json={"reason": "too_far"},
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_check_in_not_your_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test check-in for a booking that belongs to a different buyer."""
    from app.auth.service import hash_password

    other_buyer = User(
        id=uuid.uuid4(),
        email="other_buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        phone="+33600000066",
    )
    db.add(other_buyer)
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=other_buyer.id,
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

    token = buyer_token(buyer_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-in",
        json={"mechanic_present": True},
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_check_in_wrong_status(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test check-in for a booking that is not CONFIRMED."""
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
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
    )
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-in",
        json={"mechanic_present": True},
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_check_in_outside_time_window(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
    availability: Availability,
):
    """Test check-in when outside the 30-minute time window."""
    # Set availability to 3 hours ago (well outside 30-min window)
    now = datetime.now(timezone.utc)
    past = now - timedelta(hours=3)
    availability.date = past.date()
    availability.start_time = past.time()
    availability.end_time = (past + timedelta(hours=1)).time()
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
    assert response.status_code == 400
    assert "30 minutes" in response.json()["detail"]


@pytest.mark.asyncio
async def test_enter_code_not_your_booking(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test entering code for a booking that doesn't belong to this mechanic."""
    from app.auth.service import hash_password

    other_mech_user = User(
        id=uuid.uuid4(),
        email="other_mech_code@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000055",
    )
    db.add(other_mech_user)
    await db.flush()

    other_profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=other_mech_user.id,
        city="toulouse",
        city_lat=43.6047,
        city_lng=1.4442,
        max_radius_km=50,
        free_zone_km=10,
        accepted_vehicle_types=["car"],
        is_identity_verified=True,
        is_active=True,
    )
    db.add(other_profile)
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=other_profile.id,
        status=BookingStatus.AWAITING_MECHANIC_CODE,
        check_in_code="1234",
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/enter-code",
        json={"code": "1234"},
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_enter_code_wrong_status(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test entering code for a booking that is not AWAITING_MECHANIC_CODE."""
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/enter-code",
        json={"code": "1234"},
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_check_out_success(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test the full check-out flow with multipart/form data."""
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.CHECK_IN_DONE,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Peugeot",
        vehicle_model="308",
        vehicle_year=2019,
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

    checklist_json = json.dumps({
        "brakes": "ok",
        "tires": "warning",
        "fluids": "ok",
        "battery": "ok",
        "suspension": "ok",
        "body": "good",
        "exhaust": "ok",
        "lights": "ok",
        "test_drive_done": True,
        "test_drive_behavior": "normal",
        "remarks": "Some wear on front tires",
        "recommendation": "buy",
    })

    token = mechanic_token(mechanic_user)

    with patch("app.bookings.routes.upload_file", new_callable=AsyncMock) as mock_upload, \
         patch("app.bookings.routes.generate_pdf", new_callable=AsyncMock) as mock_pdf:
        mock_upload.return_value = "https://storage.emecano.dev/proofs/test.jpg"
        mock_pdf.return_value = "https://storage.emecano.dev/reports/test.pdf"

        response = await client.patch(
            f"/bookings/{booking.id}/check-out",
            params={
                "entered_plate": "AB-123-CD",
                "entered_odometer_km": 85000,
                "checklist_json": checklist_json,
                "gps_lat": 43.61,
                "gps_lng": 1.45,
            },
            files={
                "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
                "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
            },
            headers=auth_header(token),
        )

    assert response.status_code == 200
    data = response.json()
    assert "pdf_url" in data
    assert data["pdf_url"] == "https://storage.emecano.dev/reports/test.pdf"


@pytest.mark.asyncio
async def test_check_out_not_your_booking(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test check-out for a booking belonging to a different mechanic."""
    from app.auth.service import hash_password

    other_mech_user = User(
        id=uuid.uuid4(),
        email="other_mech_co@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000044",
    )
    db.add(other_mech_user)
    await db.flush()

    other_profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=other_mech_user.id,
        city="toulouse",
        city_lat=43.6047,
        city_lng=1.4442,
        max_radius_km=50,
        free_zone_km=10,
        accepted_vehicle_types=["car"],
        is_identity_verified=True,
        is_active=True,
    )
    db.add(other_profile)
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=other_profile.id,
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-out",
        params={
            "entered_plate": "AB-123-CD",
            "entered_odometer_km": 85000,
            "checklist_json": "{}",
        },
        files={
            "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
            "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
        },
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_check_out_wrong_status(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test check-out for a booking not in CHECK_IN_DONE status."""
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-out",
        params={
            "entered_plate": "AB-123-CD",
            "entered_odometer_km": 85000,
            "checklist_json": "{}",
        },
        files={
            "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
            "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
        },
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_check_out_invalid_checklist_json(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test check-out with invalid checklist JSON."""
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

    token = mechanic_token(mechanic_user)
    response = await client.patch(
        f"/bookings/{booking.id}/check-out",
        params={
            "entered_plate": "AB-123-CD",
            "entered_odometer_km": 85000,
            "checklist_json": "NOT VALID JSON {{{",
        },
        files={
            "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
            "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
        },
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "Invalid JSON" in response.json()["detail"]


@pytest.mark.asyncio
async def test_check_out_upload_error(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    buyer_user: User,
):
    """Test check-out when upload_file raises ValueError."""
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

    with patch("app.bookings.routes.upload_file", new_callable=AsyncMock) as mock_upload:
        mock_upload.side_effect = ValueError("File type not allowed")

        response = await client.patch(
            f"/bookings/{booking.id}/check-out",
            params={
                "entered_plate": "AB-123-CD",
                "entered_odometer_km": 85000,
                "checklist_json": checklist_json,
            },
            files={
                "photo_plate": ("plate.jpg", b"fake-jpeg-data", "image/jpeg"),
                "photo_odometer": ("odo.jpg", b"fake-jpeg-data", "image/jpeg"),
            },
            headers=auth_header(token),
        )

    assert response.status_code == 400
    assert "File type not allowed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_validate_booking_not_your_booking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test validating a booking that belongs to a different buyer."""
    from app.auth.service import hash_password

    other_buyer = User(
        id=uuid.uuid4(),
        email="other_buyer_val@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        phone="+33600000033",
    )
    db.add(other_buyer)
    await db.flush()

    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=other_buyer.id,
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
    response = await client.patch(
        f"/bookings/{booking.id}/validate",
        json={"validated": True},
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_validate_booking_wrong_status(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test validating a booking that is not in CHECK_OUT_DONE status."""
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

    token = buyer_token(buyer_user)
    response = await client.patch(
        f"/bookings/{booking.id}/validate",
        json={"validated": True},
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_validate_booking_dispute_without_reason_rejected(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that disputing a booking without reason/description returns 422."""
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
    # Sending validated=False without problem_reason/problem_description should be rejected
    response = await client.patch(
        f"/bookings/{booking.id}/validate",
        json={"validated": False},
        headers=auth_header(token),
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_my_bookings_as_mechanic(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test listing bookings as a mechanic user."""
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.CONFIRMED,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="MechTest",
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

    token = mechanic_token(mechanic_user)
    response = await client.get("/bookings/me", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["vehicle_brand"] == "MechTest"


@pytest.mark.asyncio
async def test_list_my_bookings_mechanic_no_profile(
    client: AsyncClient,
    db: AsyncSession,
):
    """Test listing bookings as a mechanic without a profile."""
    from app.auth.service import hash_password

    mech_no_profile = User(
        id=uuid.uuid4(),
        email="noprofile_mech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000022",
    )
    db.add(mech_no_profile)
    await db.flush()

    token = mechanic_token(mech_no_profile)
    response = await client.get("/bookings/me", headers=auth_header(token))
    assert response.status_code == 200
    assert response.json() == []
