"""Coverage tests for reports/routes.py and reports/generator.py.

Tests download tokens, receipt data building, and receipt endpoints.
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, hash_password
from app.database import get_db
from app.main import app
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.reports.routes import (
    _build_receipt_data,
    _create_download_token,
    _verify_download_token,
)
from tests.conftest import TestSessionFactory, engine
from app.database import Base


# ============ _create_download_token / _verify_download_token ============


def test_create_and_verify_download_token():
    """Round-trip: create then verify a download token."""
    booking_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    token = _create_download_token(booking_id, user_id)
    payload = _verify_download_token(token, booking_id)
    assert payload is not None
    assert payload["sub"] == user_id
    assert payload["booking_id"] == booking_id
    assert payload["type"] == "download"


def test_verify_token_wrong_booking():
    """Token verification fails when booking_id doesn't match."""
    booking_id = str(uuid.uuid4())
    token = _create_download_token(booking_id, str(uuid.uuid4()))
    result = _verify_download_token(token, str(uuid.uuid4()))
    assert result is None


def test_verify_token_invalid():
    """Invalid token returns None."""
    result = _verify_download_token("not.a.valid.token", str(uuid.uuid4()))
    assert result is None


def test_verify_token_wrong_type():
    """Token with wrong type claim returns None."""
    import jwt
    from app.config import settings

    payload = {
        "sub": str(uuid.uuid4()),
        "booking_id": str(uuid.uuid4()),
        "type": "access",  # wrong type
        "iss": "emecano",
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    result = _verify_download_token(token, payload["booking_id"])
    assert result is None


# ============ _build_receipt_data ============


@pytest.mark.asyncio
async def test_build_receipt_data_basic():
    """Build receipt data from a completed booking."""
    mock_mechanic = MagicMock()
    mock_mechanic.city = "Toulouse"

    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.COMPLETED
    mock_booking.mechanic = mock_mechanic
    mock_booking.obd_requested = False
    mock_booking.check_in_at = datetime(2026, 1, 15, 10, 0, tzinfo=timezone.utc)
    mock_booking.created_at = datetime(2026, 1, 10, tzinfo=timezone.utc)
    mock_booking.vehicle_brand = "Renault"
    mock_booking.vehicle_model = "Clio"
    mock_booking.vehicle_year = 2020
    mock_booking.base_price = Decimal("89.00")
    mock_booking.travel_fees = Decimal("10.00")
    mock_booking.total_price = Decimal("99.00")

    data = await _build_receipt_data(mock_booking)

    assert data["vehicle_brand"] == "Renault"
    assert data["mechanic_city"] == "Toulouse"
    assert data["payment_status_label"] == "Paye"
    assert data["payment_status_class"] == "status-paid"
    assert data["obd_supplement"] is None
    assert data["service_date"] == "15/01/2026"


@pytest.mark.asyncio
async def test_build_receipt_data_with_obd():
    """Build receipt data when OBD is requested."""
    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.VALIDATED
    mock_booking.mechanic = None  # No mechanic loaded
    mock_booking.obd_requested = True
    mock_booking.check_in_at = None
    mock_booking.created_at = datetime(2026, 2, 1, tzinfo=timezone.utc)
    mock_booking.vehicle_brand = "Peugeot"
    mock_booking.vehicle_model = "208"
    mock_booking.vehicle_year = 2019
    mock_booking.base_price = Decimal("89.00")
    mock_booking.travel_fees = Decimal("5.00")
    mock_booking.total_price = Decimal("124.00")

    data = await _build_receipt_data(mock_booking)

    assert data["mechanic_city"] == "Non renseigne"
    assert data["obd_supplement"] == "30.00"
    assert data["payment_status_label"] == "En cours de traitement"


@pytest.mark.asyncio
async def test_build_receipt_data_cancelled():
    """Build receipt data for cancelled booking."""
    mock_booking = MagicMock()
    mock_booking.id = uuid.uuid4()
    mock_booking.status = BookingStatus.CANCELLED
    mock_booking.mechanic = MagicMock(city="Paris")
    mock_booking.obd_requested = False
    mock_booking.check_in_at = None
    mock_booking.created_at = None  # Edge case
    mock_booking.vehicle_brand = "BMW"
    mock_booking.vehicle_model = "Serie 3"
    mock_booking.vehicle_year = 2018
    mock_booking.base_price = Decimal("89.00")
    mock_booking.travel_fees = Decimal("0.00")
    mock_booking.total_price = Decimal("89.00")

    data = await _build_receipt_data(mock_booking)

    assert data["payment_status_label"] == "Annule"
    assert data["payment_status_class"] == "status-cancelled"


# ============ Receipt endpoints (integration) ============


@pytest_asyncio.fixture
async def receipt_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionFactory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def receipt_client(receipt_db):
    async def override_get_db():
        yield receipt_db

    app.dependency_overrides[get_db] = override_get_db

    from app.utils.rate_limit import limiter
    if hasattr(limiter, "_limiter") and hasattr(limiter._limiter, "_storage"):
        limiter._limiter._storage.reset()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def receipt_setup(receipt_db):
    """Create buyer, mechanic, and booking for receipt tests."""
    buyer = User(
        id=uuid.uuid4(), email="rbuyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000010", is_verified=True,
    )
    mechanic_user = User(
        id=uuid.uuid4(), email="rmech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC, phone="+33600000011", is_verified=True,
    )
    receipt_db.add_all([buyer, mechanic_user])
    await receipt_db.flush()

    profile = MechanicProfile(
        id=uuid.uuid4(), user_id=mechanic_user.id, city="Lyon",
        city_lat=45.76, city_lng=4.83, max_radius_km=30,
        free_zone_km=5, accepted_vehicle_types=["car"],
        is_identity_verified=True, is_active=True,
        stripe_account_id="acct_test_receipt",
    )
    receipt_db.add(profile)
    await receipt_db.flush()

    booking = Booking(
        id=uuid.uuid4(), buyer_id=buyer.id, mechanic_id=profile.id,
        status=BookingStatus.COMPLETED,
        vehicle_type=VehicleType.CAR, vehicle_brand="Toyota", vehicle_model="Yaris",
        vehicle_year=2021, meeting_address="10 rue test Lyon",
        meeting_lat=45.76, meeting_lng=4.83, distance_km=5,
        base_price=Decimal("89.00"), travel_fees=Decimal("0.00"),
        total_price=Decimal("89.00"), commission_rate=Decimal("0.15"),
        commission_amount=Decimal("13.35"), mechanic_payout=Decimal("75.65"),
    )
    receipt_db.add(booking)
    await receipt_db.flush()

    return {"buyer": buyer, "booking": booking}


@pytest.mark.asyncio
async def test_get_receipt_endpoint(receipt_client, receipt_setup):
    """GET /reports/receipt/{booking_id} returns PDF."""
    buyer = receipt_setup["buyer"]
    booking = receipt_setup["booking"]
    token = create_access_token(str(buyer.id))

    with patch("app.reports.routes.generate_payment_receipt", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = b"%PDF-1.4 fake pdf content"
        resp = await receipt_client.get(
            f"/reports/receipt/{booking.id}",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/pdf"
    assert b"%PDF" in resp.content


@pytest.mark.asyncio
async def test_get_receipt_not_found(receipt_client, receipt_setup):
    """GET /reports/receipt/{random_id} returns 404."""
    buyer = receipt_setup["buyer"]
    token = create_access_token(str(buyer.id))

    resp = await receipt_client.get(
        f"/reports/receipt/{uuid.uuid4()}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_receipt_forbidden(receipt_client, receipt_setup, receipt_db):
    """Non-owner can't access receipt."""
    booking = receipt_setup["booking"]
    other_user = User(
        id=uuid.uuid4(), email="other@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000099", is_verified=True,
    )
    receipt_db.add(other_user)
    await receipt_db.flush()

    token = create_access_token(str(other_user.id))
    resp = await receipt_client.get(
        f"/reports/receipt/{booking.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_receipt_download_token_endpoint(receipt_client, receipt_setup):
    """GET /reports/receipt/{booking_id}/token returns a download token."""
    buyer = receipt_setup["buyer"]
    booking = receipt_setup["booking"]
    token = create_access_token(str(buyer.id))

    resp = await receipt_client.get(
        f"/reports/receipt/{booking.id}/token",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert "download_token" in data
    assert data["expires_in_seconds"] == 300


@pytest.mark.asyncio
async def test_download_receipt_with_valid_token(receipt_client, receipt_setup):
    """GET /reports/receipt/{booking_id}/download with valid token returns PDF."""
    buyer = receipt_setup["buyer"]
    booking = receipt_setup["booking"]
    dl_token = _create_download_token(str(booking.id), str(buyer.id))

    with patch("app.reports.routes.generate_payment_receipt", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = b"%PDF-1.4 receipt bytes"
        resp = await receipt_client.get(
            f"/reports/receipt/{booking.id}/download",
            params={"token": dl_token},
        )

    assert resp.status_code == 200
    assert "attachment" in resp.headers.get("content-disposition", "")


@pytest.mark.asyncio
async def test_download_receipt_invalid_token(receipt_client, receipt_setup):
    """Invalid download token returns 401."""
    booking = receipt_setup["booking"]

    resp = await receipt_client.get(
        f"/reports/receipt/{booking.id}/download",
        params={"token": "invalid.token.here"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_download_receipt_wrong_user(receipt_client, receipt_setup, receipt_db):
    """Download token for wrong user returns 403."""
    booking = receipt_setup["booking"]
    wrong_user_id = str(uuid.uuid4())
    dl_token = _create_download_token(str(booking.id), wrong_user_id)

    resp = await receipt_client.get(
        f"/reports/receipt/{booking.id}/download",
        params={"token": dl_token},
    )
    assert resp.status_code == 403


# ============ generate_payment_receipt ============


@pytest.mark.asyncio
async def test_generate_payment_receipt():
    """generate_payment_receipt returns PDF bytes."""
    from app.reports.generator import generate_payment_receipt

    booking_data = {
        "receipt_number": "ABCD1234",
        "service_date": "15/01/2026",
        "mechanic_city": "Toulouse",
        "vehicle_brand": "Renault",
        "vehicle_model": "Clio",
        "vehicle_year": 2020,
        "base_price": "89.00",
        "obd_supplement": None,
        "travel_fees": "10.00",
        "total_price": "99.00",
        "payment_status_label": "Paye",
        "payment_status_class": "status-paid",
    }

    pdf_bytes = await generate_payment_receipt(booking_data)
    assert isinstance(pdf_bytes, bytes)
    assert pdf_bytes[:4] == b"%PDF"
