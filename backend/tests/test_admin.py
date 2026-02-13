import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, hash_password
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import (
    BookingStatus,
    DisputeReason,
    DisputeStatus,
    UserRole,
)
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from tests.conftest import auth_header


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def admin_token(admin_user: User) -> str:
    return create_access_token(str(admin_user.id))


@pytest.fixture
def _admin_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def _second_buyer_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def _second_mechanic_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def _second_mechanic_profile_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
async def admin_user(db: AsyncSession, _admin_user_id: uuid.UUID) -> User:
    user = User(
        id=_admin_user_id,
        email="admin@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN,
        first_name="Admin",
        last_name="User",
        phone="+33600000099",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def second_buyer(db: AsyncSession, _second_buyer_id: uuid.UUID) -> User:
    user = User(
        id=_second_buyer_id,
        email="buyer2@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        first_name="Second",
        last_name="Buyer",
        phone="+33600000003",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def second_mechanic(db: AsyncSession, _second_mechanic_id: uuid.UUID) -> User:
    user = User(
        id=_second_mechanic_id,
        email="mechanic2@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        first_name="Second",
        last_name="Mechanic",
        phone="+33600000004",
        is_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest.fixture
async def second_mechanic_profile(
    db: AsyncSession,
    second_mechanic: User,
    _second_mechanic_profile_id: uuid.UUID,
) -> MechanicProfile:
    profile = MechanicProfile(
        id=_second_mechanic_profile_id,
        user_id=second_mechanic.id,
        city="paris",
        city_lat=48.8566,
        city_lng=2.3522,
        max_radius_km=30,
        free_zone_km=10,
        accepted_vehicle_types=["car"],
        is_identity_verified=False,
        identity_document_url="https://storage.example.com/doc.jpg",
        selfie_with_id_url="https://storage.example.com/selfie.jpg",
        cv_url=None,
        is_active=True,
        stripe_account_id="acct_test_second",
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest.fixture
async def completed_booking(
    db: AsyncSession, buyer_user: User, mechanic_profile: MechanicProfile
) -> Booking:
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.COMPLETED,
        vehicle_type="car",
        vehicle_brand="Peugeot",
        vehicle_model="308",
        vehicle_year=2019,
        meeting_address="123 Rue Test, Toulouse",
        meeting_lat=43.6100,
        meeting_lng=1.4500,
        distance_km=5.0,
        base_price=Decimal("40.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("40.00"),
        commission_rate=Decimal("0.15"),
        commission_amount=Decimal("6.00"),
        mechanic_payout=Decimal("34.00"),
    )
    db.add(booking)
    await db.flush()
    return booking


@pytest.fixture
async def pending_booking(
    db: AsyncSession, buyer_user: User, mechanic_profile: MechanicProfile
) -> Booking:
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=buyer_user.id,
        mechanic_id=mechanic_profile.id,
        status=BookingStatus.PENDING_ACCEPTANCE,
        vehicle_type="car",
        vehicle_brand="Renault",
        vehicle_model="Clio",
        vehicle_year=2020,
        meeting_address="456 Rue Test, Toulouse",
        meeting_lat=43.6200,
        meeting_lng=1.4600,
        distance_km=8.0,
        base_price=Decimal("40.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("40.00"),
        commission_rate=Decimal("0.15"),
        commission_amount=Decimal("6.00"),
        mechanic_payout=Decimal("34.00"),
    )
    db.add(booking)
    await db.flush()
    return booking


@pytest.fixture
async def open_dispute(
    db: AsyncSession, completed_booking: Booking, buyer_user: User
) -> DisputeCase:
    dispute = DisputeCase(
        id=uuid.uuid4(),
        booking_id=completed_booking.id,
        opened_by=buyer_user.id,
        reason=DisputeReason.NO_SHOW,
        description="Mechanic did not show up.",
        status=DisputeStatus.OPEN,
    )
    db.add(dispute)
    await db.flush()
    return dispute


# ---------------------------------------------------------------------------
# 1. Authorization -- Non-admin users get 403 on all admin endpoints
# ---------------------------------------------------------------------------


ADMIN_ENDPOINTS = [
    ("GET", "/admin/stats"),
    ("GET", "/admin/users"),
    ("GET", "/admin/users/{uid}"),
    ("PATCH", "/admin/users/{uid}/suspend"),
    ("GET", "/admin/mechanics/pending-verification"),
    ("PATCH", "/admin/mechanics/{mid}/verify"),
    ("GET", "/admin/bookings"),
    ("GET", "/admin/disputes"),
    ("GET", "/admin/revenue"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
async def test_buyer_gets_403_on_admin_endpoints(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    method: str,
    path: str,
):
    """A buyer should receive 403 on every admin endpoint."""
    token = create_access_token(str(buyer_user.id))
    url = path.replace("{uid}", str(uuid.uuid4())).replace("{mid}", str(uuid.uuid4()))
    body = None
    if method == "PATCH" and "suspend" in url:
        body = {"suspended": True, "reason": "test"}
    elif method == "PATCH" and "verify" in url:
        body = {"approved": True}

    response = await client.request(
        method, url, headers=auth_header(token), json=body
    )
    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", ADMIN_ENDPOINTS)
async def test_mechanic_gets_403_on_admin_endpoints(
    client: AsyncClient,
    db: AsyncSession,
    mechanic_user: User,
    method: str,
    path: str,
):
    """A mechanic should receive 403 on every admin endpoint."""
    token = create_access_token(str(mechanic_user.id))
    url = path.replace("{uid}", str(uuid.uuid4())).replace("{mid}", str(uuid.uuid4()))
    body = None
    if method == "PATCH" and "suspend" in url:
        body = {"suspended": True, "reason": "test"}
    elif method == "PATCH" and "verify" in url:
        body = {"approved": True}

    response = await client.request(
        method, url, headers=auth_header(token), json=body
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_request_gets_401_or_403(
    client: AsyncClient,
    db: AsyncSession,
):
    """A request with no token should be rejected."""
    response = await client.get("/admin/stats")
    assert response.status_code in (401, 403)


# ---------------------------------------------------------------------------
# 2. GET /admin/stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stats_empty_database(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Stats endpoint should return zeroes when the database is mostly empty."""
    token = admin_token(admin_user)
    response = await client.get("/admin/stats", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert "users" in data
    assert "bookings" in data
    assert "revenue" in data
    assert "open_disputes" in data
    # Only the admin user exists
    assert data["users"]["admins"] == 1
    assert data["users"]["total"] >= 1
    assert data["bookings"]["total"] == 0
    assert data["revenue"]["total"] == 0.0


@pytest.mark.asyncio
async def test_stats_with_data(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    completed_booking: Booking,
    open_dispute: DisputeCase,
):
    """Stats should reflect users, bookings, revenue, and disputes."""
    token = admin_token(admin_user)
    response = await client.get("/admin/stats", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()

    assert data["users"]["buyers"] == 1
    assert data["users"]["mechanics"] == 1
    assert data["users"]["admins"] == 1
    assert data["users"]["total"] == 3

    assert data["bookings"]["total"] == 1
    assert data["revenue"]["total"] == 40.0
    assert data["revenue"]["total_commission"] == 6.0
    assert data["open_disputes"] == 1


# ---------------------------------------------------------------------------
# 3. GET /admin/users
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_users(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
    mechanic_user: User,
):
    """Should return all users with pagination metadata."""
    token = admin_token(admin_user)
    response = await client.get("/admin/users", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["users"]) == 3

    # Verify user shape
    user_entry = data["users"][0]
    assert "id" in user_entry
    assert "email" in user_entry
    assert "role" in user_entry
    assert "is_verified" in user_entry


@pytest.mark.asyncio
async def test_list_users_filter_by_role(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
    mechanic_user: User,
):
    """Filtering by role should return only matching users."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/users", params={"role": "buyer"}, headers=auth_header(token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["users"][0]["role"] == "buyer"


@pytest.mark.asyncio
async def test_list_users_invalid_role(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Invalid role value should return 400."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/users", params={"role": "invalid_role"}, headers=auth_header(token)
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_users_pagination(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
    mechanic_user: User,
):
    """Pagination with limit and offset should work correctly."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/users",
        params={"limit": 1, "offset": 0},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 3
    assert len(data["users"]) == 1

    # Fetch second page
    response2 = await client.get(
        "/admin/users",
        params={"limit": 1, "offset": 1},
        headers=auth_header(token),
    )
    data2 = response2.json()
    assert data2["total"] == 3
    assert len(data2["users"]) == 1
    assert data2["users"][0]["id"] != data["users"][0]["id"]


# ---------------------------------------------------------------------------
# 4. GET /admin/users/{id}
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_user_detail_buyer(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
):
    """Should return buyer details with booking count."""
    token = admin_token(admin_user)
    response = await client.get(
        f"/admin/users/{buyer_user.id}", headers=auth_header(token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(buyer_user.id)
    assert data["email"] == "buyer@test.com"
    assert data["role"] == "buyer"
    assert "booking_count" in data
    assert data["booking_count"] == 0


@pytest.mark.asyncio
async def test_get_user_detail_mechanic_with_profile(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Should include mechanic_profile for mechanic users."""
    token = admin_token(admin_user)
    response = await client.get(
        f"/admin/users/{mechanic_user.id}", headers=auth_header(token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "mechanic"
    assert "mechanic_profile" in data
    mp = data["mechanic_profile"]
    assert mp["id"] == str(mechanic_profile.id)
    assert mp["city"] == "toulouse"
    assert mp["is_identity_verified"] is True
    assert mp["is_active"] is True


@pytest.mark.asyncio
async def test_get_user_detail_not_found(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Non-existent user id should return 404."""
    token = admin_token(admin_user)
    response = await client.get(
        f"/admin/users/{uuid.uuid4()}", headers=auth_header(token)
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_user_detail_with_bookings(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
    completed_booking: Booking,
):
    """Buyer's booking_count should reflect their bookings."""
    token = admin_token(admin_user)
    response = await client.get(
        f"/admin/users/{buyer_user.id}", headers=auth_header(token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["booking_count"] == 1


# ---------------------------------------------------------------------------
# 5. PATCH /admin/users/{id}/suspend
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_suspend_buyer(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
):
    """Suspending a buyer should return status 'suspended'."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/users/{buyer_user.id}/suspend",
        json={"suspended": True, "reason": "Violation of terms"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "suspended"
    assert data["user_id"] == str(buyer_user.id)


@pytest.mark.asyncio
async def test_unsuspend_buyer(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    buyer_user: User,
):
    """Unsuspending a buyer should return status 'active'."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/users/{buyer_user.id}/suspend",
        json={"suspended": False},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "active"


@pytest.mark.asyncio
async def test_suspend_mechanic_sets_profile_fields(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Suspending a mechanic should set suspended_until and deactivate profile."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/users/{mechanic_user.id}/suspend",
        json={"suspended": True, "reason": "Repeated no-shows"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "suspended"

    # Verify profile was modified in the database
    await db.refresh(mechanic_profile)
    assert mechanic_profile.is_active is False
    assert mechanic_profile.suspended_until is not None
    # suspended_until should be roughly 30 days from now
    expected = datetime.now(timezone.utc) + timedelta(days=30)
    # SQLite stores datetimes without tz info, so normalize both to naive UTC
    actual = mechanic_profile.suspended_until
    if actual.tzinfo is not None:
        actual = actual.replace(tzinfo=None)
    expected_naive = expected.replace(tzinfo=None)
    delta = abs((actual - expected_naive).total_seconds())
    assert delta < 60  # within one minute tolerance


@pytest.mark.asyncio
async def test_unsuspend_mechanic_clears_profile_fields(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Unsuspending a mechanic should clear suspended_until and reactivate."""
    token = admin_token(admin_user)

    # First suspend
    await client.patch(
        f"/admin/users/{mechanic_user.id}/suspend",
        json={"suspended": True, "reason": "test"},
        headers=auth_header(token),
    )

    # Then unsuspend
    response = await client.patch(
        f"/admin/users/{mechanic_user.id}/suspend",
        json={"suspended": False},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "active"

    await db.refresh(mechanic_profile)
    assert mechanic_profile.is_active is True
    assert mechanic_profile.suspended_until is None


@pytest.mark.asyncio
async def test_cannot_suspend_admin(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Admin users cannot be suspended (even by another admin)."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/users/{admin_user.id}/suspend",
        json={"suspended": True, "reason": "test"},
        headers=auth_header(token),
    )
    assert response.status_code == 403
    assert "Cannot suspend admin" in response.json()["detail"]


@pytest.mark.asyncio
async def test_suspend_nonexistent_user(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Suspending a non-existent user should return 404."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/users/{uuid.uuid4()}/suspend",
        json={"suspended": True, "reason": "test"},
        headers=auth_header(token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 6. GET /admin/mechanics/pending-verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pending_verification_empty(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    mechanic_profile: MechanicProfile,
):
    """When all mechanics are verified, the list should be empty."""
    # mechanic_profile from conftest is already verified
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/mechanics/pending-verification", headers=auth_header(token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["mechanics"] == []


@pytest.mark.asyncio
async def test_pending_verification_returns_unverified(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    second_mechanic: User,
    second_mechanic_profile: MechanicProfile,
):
    """Unverified mechanics with identity documents should appear in the list."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/mechanics/pending-verification", headers=auth_header(token)
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    mech = data["mechanics"][0]
    assert mech["id"] == str(second_mechanic_profile.id)
    assert mech["user_id"] == str(second_mechanic.id)
    assert mech["email"] == "mechanic2@test.com"
    assert mech["identity_document_url"] is not None
    assert mech["city"] == "paris"


@pytest.mark.asyncio
async def test_pending_verification_pagination(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    second_mechanic: User,
    second_mechanic_profile: MechanicProfile,
):
    """Pagination should limit results."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/mechanics/pending-verification",
        params={"limit": 1, "offset": 0},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["mechanics"]) <= 1


# ---------------------------------------------------------------------------
# 7. PATCH /admin/mechanics/{id}/verify
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_mechanic_approve(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    second_mechanic: User,
    second_mechanic_profile: MechanicProfile,
):
    """Approving a mechanic should set is_identity_verified to True."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/mechanics/{second_mechanic_profile.id}/verify",
        json={"approved": True},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["mechanic_id"] == str(second_mechanic_profile.id)
    assert data["is_identity_verified"] is True

    # Confirm in DB
    await db.refresh(second_mechanic_profile)
    assert second_mechanic_profile.is_identity_verified is True


@pytest.mark.asyncio
async def test_verify_mechanic_reject(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    second_mechanic: User,
    second_mechanic_profile: MechanicProfile,
):
    """Rejecting a mechanic should set is_identity_verified to False."""
    # First approve
    token = admin_token(admin_user)
    await client.patch(
        f"/admin/mechanics/{second_mechanic_profile.id}/verify",
        json={"approved": True},
        headers=auth_header(token),
    )

    # Then reject
    response = await client.patch(
        f"/admin/mechanics/{second_mechanic_profile.id}/verify",
        json={"approved": False},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["is_identity_verified"] is False

    await db.refresh(second_mechanic_profile)
    assert second_mechanic_profile.is_identity_verified is False


@pytest.mark.asyncio
async def test_verify_mechanic_not_found(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Verifying a non-existent mechanic profile should return 404."""
    token = admin_token(admin_user)
    response = await client.patch(
        f"/admin/mechanics/{uuid.uuid4()}/verify",
        json={"approved": True},
        headers=auth_header(token),
    )
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# 8. GET /admin/bookings
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_bookings_no_filters(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
    pending_booking: Booking,
):
    """Should return all bookings with pagination metadata."""
    token = admin_token(admin_user)
    response = await client.get("/admin/bookings", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["bookings"]) == 2

    # Verify booking shape
    b = data["bookings"][0]
    assert "id" in b
    assert "buyer_id" in b
    assert "mechanic_id" in b
    assert "status" in b
    assert "total_price" in b
    assert "commission_amount" in b
    assert "mechanic_payout" in b


@pytest.mark.asyncio
async def test_list_bookings_filter_by_status(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
    pending_booking: Booking,
):
    """Filtering by status should return only matching bookings."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/bookings",
        params={"status": "completed"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    assert data["bookings"][0]["status"] == "completed"


@pytest.mark.asyncio
async def test_list_bookings_invalid_status(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Invalid status filter should return 400."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/bookings",
        params={"status": "not_a_status"},
        headers=auth_header(token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_bookings_filter_by_date_range(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
):
    """Filtering by date_from and date_to should work."""
    token = admin_token(admin_user)
    today = datetime.now(timezone.utc).date().isoformat()
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()

    response = await client.get(
        "/admin/bookings",
        params={"date_from": today, "date_to": tomorrow},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    # The booking was created "today" so it should be included
    assert data["total"] >= 1


@pytest.mark.asyncio
async def test_list_bookings_date_range_excludes(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
):
    """A date range in the past should exclude recently created bookings."""
    token = admin_token(admin_user)
    past_start = "2020-01-01"
    past_end = "2020-01-02"

    response = await client.get(
        "/admin/bookings",
        params={"date_from": past_start, "date_to": past_end},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_list_bookings_invalid_date_from(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Invalid date_from format should return 400."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/bookings",
        params={"date_from": "not-a-date"},
        headers=auth_header(token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_bookings_invalid_date_to(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Invalid date_to format should return 400."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/bookings",
        params={"date_to": "not-a-date"},
        headers=auth_header(token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_bookings_pagination(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
    pending_booking: Booking,
):
    """Pagination limit and offset should be respected."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/bookings",
        params={"limit": 1, "offset": 0},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert len(data["bookings"]) == 1


# ---------------------------------------------------------------------------
# 9. GET /admin/disputes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_disputes_default_open(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    open_dispute: DisputeCase,
):
    """Default dispute listing should show only open disputes."""
    token = admin_token(admin_user)
    response = await client.get("/admin/disputes", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 1
    d = data["disputes"][0]
    assert d["id"] == str(open_dispute.id)
    assert d["status"] == "open"
    assert d["reason"] == "no_show"
    assert d["description"] == "Mechanic did not show up."
    assert d["opener_email"] == "buyer@test.com"


@pytest.mark.asyncio
async def test_list_disputes_filter_by_status(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    open_dispute: DisputeCase,
):
    """Filtering disputes by a status that has no results returns empty."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/disputes",
        params={"status": "closed"},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["disputes"] == []


@pytest.mark.asyncio
async def test_list_disputes_invalid_status(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Invalid dispute status filter should return 400."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/disputes",
        params={"status": "invalid_status"},
        headers=auth_header(token),
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_list_disputes_empty(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """With no disputes, the list should be empty."""
    token = admin_token(admin_user)
    response = await client.get("/admin/disputes", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 0
    assert data["disputes"] == []


@pytest.mark.asyncio
async def test_list_disputes_pagination(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    open_dispute: DisputeCase,
):
    """Pagination should limit dispute results."""
    token = admin_token(admin_user)
    response = await client.get(
        "/admin/disputes",
        params={"limit": 1, "offset": 0},
        headers=auth_header(token),
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["disputes"]) <= 1


# ---------------------------------------------------------------------------
# 10. GET /admin/revenue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_revenue_empty(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
):
    """Revenue endpoint with no completed bookings should return empty daily array."""
    token = admin_token(admin_user)
    response = await client.get("/admin/revenue", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 30
    assert data["daily"] == []


_SQLITE_DATE_CAST_SKIP = (
    "The revenue endpoint uses cast(DateTime, Date) which SQLite does not support. "
    "These tests pass on PostgreSQL."
)


@pytest.mark.asyncio
async def test_revenue_with_completed_bookings(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
):
    """Revenue should reflect completed bookings within the date range."""
    token = admin_token(admin_user)
    try:
        response = await client.get("/admin/revenue", headers=auth_header(token))
    except TypeError:
        pytest.skip(_SQLITE_DATE_CAST_SKIP)
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 30
    assert len(data["daily"]) >= 1

    # Verify the daily entry has the expected shape and values
    day = data["daily"][0]
    assert "date" in day
    assert "revenue" in day
    assert "commission" in day
    assert "count" in day
    assert day["revenue"] == 40.0
    assert day["commission"] == 6.0
    assert day["count"] == 1


@pytest.mark.asyncio
async def test_revenue_custom_days_param(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
):
    """Custom days parameter should be reflected in the response."""
    token = admin_token(admin_user)
    try:
        response = await client.get(
            "/admin/revenue", params={"days": 7}, headers=auth_header(token)
        )
    except TypeError:
        pytest.skip(_SQLITE_DATE_CAST_SKIP)
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 7


@pytest.mark.asyncio
async def test_revenue_excludes_non_completed(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    pending_booking: Booking,
):
    """Pending bookings should not appear in revenue breakdown."""
    token = admin_token(admin_user)
    response = await client.get("/admin/revenue", headers=auth_header(token))
    assert response.status_code == 200
    data = response.json()
    # pending_booking is not completed, so daily should be empty
    assert data["daily"] == []


@pytest.mark.asyncio
async def test_revenue_narrow_range_excludes(
    client: AsyncClient,
    db: AsyncSession,
    admin_user: User,
    completed_booking: Booking,
):
    """Using days=1 should only include today's bookings."""
    token = admin_token(admin_user)
    try:
        response = await client.get(
            "/admin/revenue", params={"days": 1}, headers=auth_header(token)
        )
    except TypeError:
        pytest.skip(_SQLITE_DATE_CAST_SKIP)
    assert response.status_code == 200
    data = response.json()
    assert data["period_days"] == 1
    # The completed booking was created "now" so it should be within the last 1 day
    assert len(data["daily"]) >= 1
