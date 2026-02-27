"""Integration tests for the Buyer Demand feature (reverse-booking system)."""

import uuid
from datetime import date, datetime, time, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token
from app.models.buyer_demand import BuyerDemand, DemandInterest
from app.models.enums import DemandStatus, UserRole, VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.auth.service import hash_password


# ────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def buyer2(db: AsyncSession) -> User:
    """A second buyer user for isolation tests."""
    user = User(
        id=uuid.uuid4(),
        email="buyer2@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER,
        phone="+33600000099",
        is_verified=True,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def mechanic_user2(db: AsyncSession) -> User:
    """A second mechanic user for multi-mechanic tests."""
    user = User(
        id=uuid.uuid4(),
        email="mechanic2@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC,
        phone="+33600000003",
        is_verified=True,
        is_active=True,
    )
    db.add(user)
    await db.flush()
    return user


@pytest_asyncio.fixture
async def mechanic_profile2(db: AsyncSession, mechanic_user2: User) -> MechanicProfile:
    """A second mechanic profile (far away, different city)."""
    profile = MechanicProfile(
        id=uuid.uuid4(),
        user_id=mechanic_user2.id,
        city="paris",
        city_lat=48.8566,
        city_lng=2.3522,
        max_radius_km=10,
        free_zone_km=5,
        accepted_vehicle_types=["car"],
        is_identity_verified=True,
        is_active=True,
        stripe_account_id="acct_test_fixture2",
    )
    db.add(profile)
    await db.flush()
    return profile


@pytest_asyncio.fixture
async def open_demand(db: AsyncSession, buyer_user: User) -> BuyerDemand:
    """An existing open demand posted by buyer_user."""
    tomorrow = date.today() + timedelta(days=1)
    demand = BuyerDemand(
        buyer_id=buyer_user.id,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Renault",
        vehicle_model="Clio",
        vehicle_year=2018,
        vehicle_plate="AB-123-CD",
        meeting_address="1 rue de la Paix, Toulouse",
        meeting_lat=43.6000,
        meeting_lng=1.4400,
        desired_date=tomorrow,
        start_time=time(10, 0),
        end_time=time(12, 0),
        obd_requested=False,
        message="Please check brakes",
        status=DemandStatus.OPEN,
        created_at=datetime.now(timezone.utc),
        expires_at=datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59, tzinfo=timezone.utc),
    )
    db.add(demand)
    await db.flush()
    return demand


def _auth(user: User) -> dict:
    token = create_access_token(str(user.id))
    return {"Authorization": f"Bearer {token}"}


# ────────────────────────────────────────────────────────────────────
# POST /demands — create demand
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buyer_creates_demand(
    client: AsyncClient,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Buyer can create a demand; nearby mechanic is notified."""
    tomorrow = date.today() + timedelta(days=1)
    payload = {
        "vehicle_type": "car",
        "vehicle_brand": "Renault",
        "vehicle_model": "Clio",
        "vehicle_year": 2018,
        "vehicle_plate": "AB-123-CD",
        "meeting_address": "1 rue de la Paix, Toulouse",
        "meeting_lat": 43.6000,
        "meeting_lng": 1.4400,
        "desired_date": str(tomorrow),
        "start_time": "09:00",
        "end_time": "11:00",
        "obd_requested": False,
        "message": "Please check brakes",
    }
    resp = await client.post("/demands", json=payload, headers=_auth(buyer_user))
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["vehicle_brand"] == "Renault"
    assert data["status"] == "open"
    assert data["interest_count"] == 0
    assert data["buyer_name"] is not None


@pytest.mark.asyncio
async def test_mechanic_cannot_create_demand(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Mechanics are not allowed to post demands."""
    tomorrow = date.today() + timedelta(days=1)
    payload = {
        "vehicle_type": "car",
        "vehicle_brand": "Peugeot",
        "vehicle_model": "208",
        "vehicle_year": 2020,
        "meeting_address": "Some address",
        "meeting_lat": 43.6,
        "meeting_lng": 1.44,
        "desired_date": str(tomorrow),
        "start_time": "09:00",
        "end_time": "11:00",
    }
    resp = await client.post("/demands", json=payload, headers=_auth(mechanic_user))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_create_demand_past_date_rejected(
    client: AsyncClient,
    buyer_user: User,
):
    """A demand with a past desired_date is rejected."""
    yesterday = date.today() - timedelta(days=1)
    payload = {
        "vehicle_type": "car",
        "vehicle_brand": "Renault",
        "vehicle_model": "Clio",
        "vehicle_year": 2018,
        "meeting_address": "1 rue de la Paix",
        "meeting_lat": 43.6,
        "meeting_lng": 1.44,
        "desired_date": str(yesterday),
        "start_time": "09:00",
        "end_time": "11:00",
    }
    resp = await client.post("/demands", json=payload, headers=_auth(buyer_user))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_demand_end_before_start_rejected(
    client: AsyncClient,
    buyer_user: User,
):
    """end_time must be after start_time."""
    tomorrow = date.today() + timedelta(days=1)
    payload = {
        "vehicle_type": "car",
        "vehicle_brand": "Renault",
        "vehicle_model": "Clio",
        "vehicle_year": 2018,
        "meeting_address": "1 rue de la Paix",
        "meeting_lat": 43.6,
        "meeting_lng": 1.44,
        "desired_date": str(tomorrow),
        "start_time": "11:00",
        "end_time": "09:00",  # before start
    }
    resp = await client.post("/demands", json=payload, headers=_auth(buyer_user))
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_create_demand_invalid_year(client: AsyncClient, buyer_user: User):
    """vehicle_year cannot be before 1950."""
    tomorrow = date.today() + timedelta(days=1)
    payload = {
        "vehicle_type": "car",
        "vehicle_brand": "Ford",
        "vehicle_model": "Model T",
        "vehicle_year": 1900,
        "meeting_address": "Address",
        "meeting_lat": 43.6,
        "meeting_lng": 1.44,
        "desired_date": str(tomorrow),
        "start_time": "09:00",
        "end_time": "11:00",
    }
    resp = await client.post("/demands", json=payload, headers=_auth(buyer_user))
    assert resp.status_code == 422


# ────────────────────────────────────────────────────────────────────
# GET /demands/mine — buyer lists their demands
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buyer_lists_own_demands(
    client: AsyncClient,
    buyer_user: User,
    open_demand: BuyerDemand,
):
    """Buyer sees only their own demands."""
    resp = await client.get("/demands/mine", headers=_auth(buyer_user))
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    ids = [d["id"] for d in data]
    assert str(open_demand.id) in ids


@pytest.mark.asyncio
async def test_buyer2_cannot_see_buyer1_demands(
    client: AsyncClient,
    buyer2: User,
    open_demand: BuyerDemand,
):
    """A different buyer's /mine endpoint should not return another buyer's demand."""
    resp = await client.get("/demands/mine", headers=_auth(buyer2))
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert str(open_demand.id) not in ids


@pytest.mark.asyncio
async def test_mechanic_cannot_list_mine(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Mechanics cannot access /demands/mine (buyer-only endpoint)."""
    resp = await client.get("/demands/mine", headers=_auth(mechanic_user))
    assert resp.status_code == 403


# ────────────────────────────────────────────────────────────────────
# GET /demands/nearby — mechanic sees nearby demands
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mechanic_sees_nearby_demand(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanic within radius sees the open demand."""
    resp = await client.get("/demands/nearby", headers=_auth(mechanic_user))
    assert resp.status_code == 200
    data = resp.json()
    ids = [d["id"] for d in data]
    assert str(open_demand.id) in ids
    # distance_km should be populated
    matching = next(d for d in data if d["id"] == str(open_demand.id))
    assert matching["distance_km"] is not None


@pytest.mark.asyncio
async def test_mechanic_far_away_does_not_see_demand(
    client: AsyncClient,
    mechanic_user2: User,
    mechanic_profile2: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanic too far away (Paris vs Toulouse demand) does not see the demand."""
    resp = await client.get("/demands/nearby", headers=_auth(mechanic_user2))
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    # Paris to Toulouse is ~600km, which exceeds max_radius_km=10
    assert str(open_demand.id) not in ids


@pytest.mark.asyncio
async def test_buyer_cannot_list_nearby(
    client: AsyncClient,
    buyer_user: User,
    open_demand: BuyerDemand,
):
    """Buyers cannot access /demands/nearby (mechanic-only endpoint)."""
    resp = await client.get("/demands/nearby", headers=_auth(buyer_user))
    assert resp.status_code == 403


# ────────────────────────────────────────────────────────────────────
# GET /demands/{demand_id} — detail view
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buyer_sees_demand_detail(
    client: AsyncClient,
    buyer_user: User,
    open_demand: BuyerDemand,
):
    """Buyer can view detail of their own demand."""
    resp = await client.get(f"/demands/{open_demand.id}", headers=_auth(buyer_user))
    assert resp.status_code == 200
    data = resp.json()
    assert "demand" in data
    assert "interests" in data
    assert data["demand"]["id"] == str(open_demand.id)
    assert isinstance(data["interests"], list)


@pytest.mark.asyncio
async def test_mechanic_sees_demand_detail(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanic can view demand detail with their interest status."""
    resp = await client.get(f"/demands/{open_demand.id}", headers=_auth(mechanic_user))
    assert resp.status_code == 200
    data = resp.json()
    assert "demand" in data
    assert "my_interest" in data
    assert data["my_interest"] is None  # no interest yet


@pytest.mark.asyncio
async def test_buyer_cannot_see_another_buyers_demand(
    client: AsyncClient,
    buyer2: User,
    open_demand: BuyerDemand,
):
    """A buyer cannot view another buyer's demand."""
    resp = await client.get(f"/demands/{open_demand.id}", headers=_auth(buyer2))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_demand_not_found(client: AsyncClient, buyer_user: User):
    """Returns 404 for a non-existent demand."""
    resp = await client.get(f"/demands/{uuid.uuid4()}", headers=_auth(buyer_user))
    assert resp.status_code == 404


# ────────────────────────────────────────────────────────────────────
# POST /demands/{demand_id}/interest — mechanic expresses interest
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mechanic_expresses_interest(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanic can express interest in a nearby demand."""
    resp = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["demand_id"] == str(open_demand.id)
    assert data["mechanic_id"] == str(mechanic_profile.id)
    assert data["proposal_id"] is not None
    assert data["mechanic_name"] is not None


@pytest.mark.asyncio
async def test_mechanic_cannot_express_interest_twice(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Duplicate interest from same mechanic is rejected with 409."""
    resp1 = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user),
    )
    assert resp1.status_code == 201

    resp2 = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user),
    )
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_mechanic_far_cannot_express_interest(
    client: AsyncClient,
    mechanic_user2: User,
    mechanic_profile2: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanic outside radius cannot express interest."""
    resp = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user2),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_buyer_cannot_express_interest(
    client: AsyncClient,
    buyer_user: User,
    open_demand: BuyerDemand,
):
    """Buyers cannot express interest in demands."""
    resp = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(buyer_user),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_interest_on_nonexistent_demand(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
):
    """Returns 404 for interest on a non-existent demand."""
    resp = await client.post(
        f"/demands/{uuid.uuid4()}/interest",
        headers=_auth(mechanic_user),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_interest_shows_in_demand_detail_for_buyer(
    client: AsyncClient,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """After mechanic expresses interest, buyer sees it in demand detail."""
    # Mechanic expresses interest
    interest_resp = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user),
    )
    assert interest_resp.status_code == 201

    # Buyer checks detail
    detail_resp = await client.get(
        f"/demands/{open_demand.id}", headers=_auth(buyer_user)
    )
    assert detail_resp.status_code == 200
    data = detail_resp.json()
    assert data["demand"]["interest_count"] == 1
    assert len(data["interests"]) == 1
    interest = data["interests"][0]
    assert interest["mechanic_name"] is not None
    assert interest["proposal_id"] is not None


@pytest.mark.asyncio
async def test_interest_shows_in_mechanic_detail(
    client: AsyncClient,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """After expressing interest, mechanic sees my_interest in demand detail."""
    await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user),
    )

    resp = await client.get(
        f"/demands/{open_demand.id}", headers=_auth(mechanic_user)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["my_interest"] is not None
    assert data["my_interest"]["proposal_id"] is not None


# ────────────────────────────────────────────────────────────────────
# PATCH /demands/{demand_id}/close — buyer closes demand
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_buyer_closes_demand(
    client: AsyncClient,
    buyer_user: User,
    open_demand: BuyerDemand,
):
    """Buyer can close their own open demand."""
    resp = await client.patch(
        f"/demands/{open_demand.id}/close", headers=_auth(buyer_user)
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "closed"
    assert data["demand_id"] == str(open_demand.id)


@pytest.mark.asyncio
async def test_buyer_cannot_close_twice(
    client: AsyncClient,
    buyer_user: User,
    open_demand: BuyerDemand,
):
    """Closing an already-closed demand returns 409."""
    await client.patch(f"/demands/{open_demand.id}/close", headers=_auth(buyer_user))
    resp2 = await client.patch(
        f"/demands/{open_demand.id}/close", headers=_auth(buyer_user)
    )
    assert resp2.status_code == 409


@pytest.mark.asyncio
async def test_buyer2_cannot_close_buyer1_demand(
    client: AsyncClient,
    buyer2: User,
    open_demand: BuyerDemand,
):
    """A buyer cannot close another buyer's demand."""
    resp = await client.patch(
        f"/demands/{open_demand.id}/close", headers=_auth(buyer2)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_mechanic_cannot_close_demand(
    client: AsyncClient,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanics cannot close demands."""
    resp = await client.patch(
        f"/demands/{open_demand.id}/close", headers=_auth(mechanic_user)
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_closed_demand_not_in_nearby(
    client: AsyncClient,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """After closing, demand no longer appears in nearby list."""
    # Close the demand
    await client.patch(f"/demands/{open_demand.id}/close", headers=_auth(buyer_user))

    # Mechanic checks nearby
    resp = await client.get("/demands/nearby", headers=_auth(mechanic_user))
    assert resp.status_code == 200
    ids = [d["id"] for d in resp.json()]
    assert str(open_demand.id) not in ids


@pytest.mark.asyncio
async def test_interest_on_closed_demand_rejected(
    client: AsyncClient,
    buyer_user: User,
    mechanic_user: User,
    mechanic_profile: MechanicProfile,
    open_demand: BuyerDemand,
):
    """Mechanic cannot express interest once the demand is closed."""
    # Close the demand first
    await client.patch(f"/demands/{open_demand.id}/close", headers=_auth(buyer_user))

    # Mechanic tries to express interest
    resp = await client.post(
        f"/demands/{open_demand.id}/interest",
        headers=_auth(mechanic_user),
    )
    assert resp.status_code == 409


# ────────────────────────────────────────────────────────────────────
# Unauthenticated access
# ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unauthenticated_create_demand(client: AsyncClient):
    """Creating a demand without auth returns 403."""
    tomorrow = date.today() + timedelta(days=1)
    resp = await client.post(
        "/demands",
        json={
            "vehicle_type": "car",
            "vehicle_brand": "Renault",
            "vehicle_model": "Clio",
            "vehicle_year": 2018,
            "meeting_address": "Address",
            "meeting_lat": 43.6,
            "meeting_lng": 1.44,
            "desired_date": str(tomorrow),
            "start_time": "09:00",
            "end_time": "11:00",
        },
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_unauthenticated_list_nearby(client: AsyncClient):
    """Accessing /nearby without auth returns 403."""
    resp = await client.get("/demands/nearby")
    assert resp.status_code == 403
