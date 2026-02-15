import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.message import Message
from app.models.user import User
from tests.conftest import auth_header, buyer_token, mechanic_token


def _make_booking(buyer_id, mechanic_id, status=BookingStatus.CONFIRMED):
    return Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_id,
        mechanic_id=mechanic_id,
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
    )


@pytest.mark.asyncio
async def test_get_templates(client: AsyncClient):
    """GET /messages/templates returns template categories."""
    response = await client.get("/messages/templates")
    assert response.status_code == 200
    data = response.json()
    assert len(data) >= 4
    categories = [item["category"] for item in data]
    assert "Retard" in categories
    assert "Localisation" in categories
    assert "Autre" in categories


@pytest.mark.asyncio
async def test_get_booking_messages_empty(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """GET /bookings/{id}/messages returns empty list when no messages exist."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.get(
        f"/bookings/{booking.id}/messages",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_get_booking_messages_with_messages(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """GET /bookings/{id}/messages returns existing messages."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    msg = Message(
        booking_id=booking.id,
        sender_id=buyer_user.id,
        is_template=True,
        content="Je serai en retard de 10 minutes environ",
    )
    db.add(msg)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.get(
        f"/bookings/{booking.id}/messages",
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["content"] == "Je serai en retard de 10 minutes environ"
    assert data[0]["is_template"] is True


@pytest.mark.asyncio
async def test_send_template_message(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """POST /bookings/{id}/messages sends a template message successfully."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "Je serai en retard de 10 minutes",
            "is_template": True,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["is_template"] is True
    assert data["content"] == "Je serai en retard de 10 minutes"
    assert data["sender_id"] == str(buyer_user.id)


@pytest.mark.asyncio
async def test_send_invalid_template_message(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """POST /bookings/{id}/messages rejects unknown template content."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "This is not a real template",
            "is_template": True,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 400
    assert "Invalid template" in response.json()["detail"]


@pytest.mark.asyncio
async def test_send_custom_message(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """POST /bookings/{id}/messages sends a custom (non-template) message."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "Bonjour, petite question sur le rendez-vous",
            "is_template": False,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    assert data["is_template"] is False


@pytest.mark.asyncio
async def test_custom_message_multiple_allowed(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Multiple custom messages are allowed per user per booking."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    # First custom message
    existing_msg = Message(
        booking_id=booking.id,
        sender_id=buyer_user.id,
        is_template=False,
        content="First custom message",
    )
    db.add(existing_msg)
    await db.flush()

    token = buyer_token(buyer_user)
    # Second custom message should also succeed
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "Second custom message",
            "is_template": False,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    assert response.json()["content"] == "Second custom message"


@pytest.mark.asyncio
async def test_custom_message_contact_masking(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Custom messages should have contact info masked."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "Appelez-moi au 06 12 34 56 78 ou test@email.com",
            "is_template": False,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201
    data = response.json()
    # Contact info should be masked
    assert "06 12 34 56 78" not in data["content"]
    assert "test@email.com" not in data["content"]
    assert "MASQUE" in data["content"]


@pytest.mark.asyncio
async def test_send_message_wrong_booking_status(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Messaging not available for non-active booking statuses."""
    booking = _make_booking(
        buyer_user.id, mechanic_profile.id, status=BookingStatus.CANCELLED
    )
    db.add(booking)
    await db.flush()

    token = buyer_token(buyer_user)
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "Je serai en retard de 10 minutes environ",
            "is_template": True,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_messages_requires_auth(client: AsyncClient):
    """Messaging endpoints require authentication."""
    booking_id = uuid.uuid4()
    response = await client.get(f"/bookings/{booking_id}/messages")
    assert response.status_code in (401, 403)


@pytest.mark.asyncio
async def test_get_messages_booking_not_found(
    client: AsyncClient,
    buyer_user: User,
):
    """GET messages for non-existent booking returns 404."""
    token = buyer_token(buyer_user)
    response = await client.get(
        f"/bookings/{uuid.uuid4()}/messages",
        headers=auth_header(token),
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_messages_not_participant(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Non-participant cannot access booking messages."""
    from app.auth.service import hash_password

    other_buyer = User(
        id=uuid.uuid4(),
        email="other_msg_buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        phone="+33600000111",
        is_verified=True,
    )
    db.add(other_buyer)
    await db.flush()

    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = buyer_token(other_buyer)
    response = await client.get(
        f"/bookings/{booking.id}/messages",
        headers=auth_header(token),
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_mechanic_can_send_template_message(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Mechanic participant can send template messages."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.post(
        f"/bookings/{booking.id}/messages",
        json={
            "content": "Je suis arrivé",
            "is_template": True,
        },
        headers=auth_header(token),
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_mechanic_can_read_messages(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Mechanic participant can read booking messages."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    token = mechanic_token(mechanic_user)
    response = await client.get(
        f"/bookings/{booking.id}/messages",
        headers=auth_header(token),
    )
    assert response.status_code == 200
