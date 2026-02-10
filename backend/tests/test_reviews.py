import uuid
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import hash_password
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.review import Review
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


def _make_completed_booking(
    db: AsyncSession,
    buyer_id: uuid.UUID,
    mechanic_profile: MechanicProfile,
) -> Booking:
    """Helper to create a completed booking for review tests."""
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_id,
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
    return booking


@pytest.mark.asyncio
async def test_create_review_as_buyer(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a buyer can create a public review for a completed booking."""
    booking = _make_completed_booking(db, buyer_user.id, mechanic_profile)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 5,
            "comment": "Great inspection!",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["rating"] == 5
    assert data["comment"] == "Great inspection!"
    assert data["is_public"] is True
    assert data["reviewer_id"] == str(buyer_user.id)
    assert data["reviewee_id"] == str(mechanic_user.id)


@pytest.mark.asyncio
async def test_create_review_as_mechanic(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a mechanic can create a private review for a completed booking."""
    booking = _make_completed_booking(db, buyer_user.id, mechanic_profile)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "Buyer was nice.",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["rating"] == 4
    assert data["is_public"] is False
    assert data["reviewer_id"] == str(mechanic_user.id)
    assert data["reviewee_id"] == str(buyer_user.id)


@pytest.mark.asyncio
async def test_create_review_booking_not_found(
    client: AsyncClient,
    buyer_user: User,
):
    """Test creating a review for a non-existent booking."""
    token = buyer_token(buyer_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(uuid.uuid4()),
            "rating": 5,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 404
    assert "Booking not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_review_booking_not_completed(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test creating a review for a booking that is not in COMPLETED status."""
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
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 5,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 409
    assert "completed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_create_review_already_reviewed(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test creating a duplicate review for the same booking."""
    booking = _make_completed_booking(db, buyer_user.id, mechanic_profile)
    await db.flush()

    # Create first review
    review = Review(
        id=uuid.uuid4(),
        booking_id=booking.id,
        reviewer_id=buyer_user.id,
        reviewee_id=mechanic_user.id,
        rating=5,
        comment="First review",
        is_public=True,
    )
    db.add(review)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 409
    assert "Already reviewed" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_review_not_participant(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test creating a review by a buyer who is not the booking's buyer."""
    other_buyer = User(
        id=uuid.uuid4(),
        email="review_other_buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        phone="+33600000111",
    )
    db.add(other_buyer)
    await db.flush()

    booking = _make_completed_booking(db, other_buyer.id, mechanic_profile)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 5,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "Not a participant" in response.json()["detail"]


@pytest.mark.asyncio
async def test_create_review_mechanic_not_participant(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that a mechanic cannot review a booking they are not part of."""
    # Create another mechanic's profile
    other_mech_user = User(
        id=uuid.uuid4(),
        email="review_other_mech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000222",
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

    # Booking belongs to other_profile
    booking = _make_completed_booking(db, buyer_user.id, other_profile)
    await db.flush()

    # But our mechanic_user tries to review it
    token = mechanic_token(mechanic_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "Not a participant" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_reviews(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test listing public reviews for a mechanic."""
    booking = _make_completed_booking(db, buyer_user.id, mechanic_profile)
    await db.flush()

    review = Review(
        id=uuid.uuid4(),
        booking_id=booking.id,
        reviewer_id=buyer_user.id,
        reviewee_id=mechanic_user.id,
        rating=5,
        comment="Excellent",
        is_public=True,
    )
    db.add(review)
    await db.flush()

    response = await client.get(
        "/reviews",
        params={"mechanic_id": str(mechanic_profile.id)},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["rating"] == 5
    assert data[0]["comment"] == "Excellent"


@pytest.mark.asyncio
async def test_list_reviews_mechanic_not_found(
    client: AsyncClient,
):
    """Test listing reviews for a non-existent mechanic."""
    response = await client.get(
        "/reviews",
        params={"mechanic_id": str(uuid.uuid4())},
    )
    assert response.status_code == 404
    assert "Mechanic not found" in response.json()["detail"]


@pytest.mark.asyncio
async def test_list_reviews_with_pagination(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test listing reviews with offset and limit pagination."""
    # Create 3 reviews
    for i in range(3):
        b = _make_completed_booking(db, buyer_user.id, mechanic_profile)
        await db.flush()
        review = Review(
            id=uuid.uuid4(),
            booking_id=b.id,
            reviewer_id=buyer_user.id,
            reviewee_id=mechanic_user.id,
            rating=i + 3,
            comment=f"Review {i}",
            is_public=True,
        )
        db.add(review)
    await db.flush()

    # Fetch with limit=2
    response = await client.get(
        "/reviews",
        params={"mechanic_id": str(mechanic_profile.id), "limit": 2, "offset": 0},
    )
    assert response.status_code == 200
    assert len(response.json()) == 2

    # Fetch with offset=2
    response = await client.get(
        "/reviews",
        params={"mechanic_id": str(mechanic_profile.id), "limit": 10, "offset": 2},
    )
    assert response.status_code == 200
    assert len(response.json()) == 1


@pytest.mark.asyncio
async def test_create_review_updates_mechanic_rating(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Test that creating a buyer review updates the mechanic's average rating."""
    booking = _make_completed_booking(db, buyer_user.id, mechanic_profile)
    await db.flush()

    assert mechanic_profile.rating_avg == 0.0
    assert mechanic_profile.total_reviews == 0

    token = buyer_token(buyer_user)
    response = await client.post(
        "/reviews",
        json={
            "booking_id": str(booking.id),
            "rating": 4,
            "comment": "Good",
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201

    await db.refresh(mechanic_profile)
    assert mechanic_profile.rating_avg == 4.0
    assert mechanic_profile.total_reviews == 1
