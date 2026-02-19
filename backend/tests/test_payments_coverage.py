import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import create_access_token, hash_password
from app.database import Base, get_db
from app.main import app
from app.models.booking import Booking
from app.models.enums import BookingStatus, DisputeReason, DisputeStatus, UserRole, VehicleType
from app.models.dispute import DisputeCase
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from tests.conftest import TestSessionFactory, engine, auth_header, buyer_token, mechanic_token


def _make_booking(buyer_id, mechanic_id, status=BookingStatus.PENDING_ACCEPTANCE, stripe_pi="pi_test_123"):
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
        stripe_payment_intent_id=stripe_pi,
    )


@pytest.mark.asyncio
async def test_webhook_payment_intent_succeeded(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: payment_intent.succeeded moves validated booking to completed."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id, status=BookingStatus.VALIDATED)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": booking.stripe_payment_intent_id,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_payment_intent_succeeded_non_validated(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: payment_intent.succeeded with non-VALIDATED booking just logs."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id, status=BookingStatus.CONFIRMED)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": booking.stripe_payment_intent_id,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_payment_intent_payment_failed(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: payment_intent.payment_failed cancels pending booking."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id, status=BookingStatus.PENDING_ACCEPTANCE)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "payment_intent.payment_failed",
        "data": {
            "object": {
                "id": booking.stripe_payment_intent_id,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_charge_dispute_created(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: charge.dispute.created logs the dispute."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id, status=BookingStatus.COMPLETED)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "charge.dispute.created",
        "data": {
            "object": {
                "id": "dp_test_123",
                "payment_intent": booking.stripe_payment_intent_id,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


@pytest.mark.asyncio
async def test_webhook_charge_dispute_created_no_pi(
    client: AsyncClient,
    db: AsyncSession,
):
    """Webhook: charge.dispute.created without payment_intent still returns ok."""
    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "charge.dispute.created",
        "data": {
            "object": {
                "id": "dp_test_456",
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_idempotency(
    client: AsyncClient,
    db: AsyncSession,
):
    """Webhook: duplicate events are skipped."""
    event_id = f"evt_{uuid.uuid4().hex[:16]}"

    # Pre-record this event
    db.add(ProcessedWebhookEvent(event_id=event_id))
    await db.flush()

    event = {
        "id": event_id,
        "type": "payment_intent.succeeded",
        "data": {"object": {"id": "pi_xxx"}},
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "already_processed"


@pytest.mark.asyncio
async def test_webhook_amount_capturable_updated(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: payment_intent.amount_capturable_updated logs authorization."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "payment_intent.amount_capturable_updated",
        "data": {
            "object": {
                "id": booking.stripe_payment_intent_id,
                "amount_capturable": 5000,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_payment_intent_canceled(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: payment_intent.canceled cancels pending/confirmed booking."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id, status=BookingStatus.CONFIRMED)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "payment_intent.canceled",
        "data": {
            "object": {
                "id": booking.stripe_payment_intent_id,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_charge_refund_created(
    client: AsyncClient,
    db: AsyncSession,
    buyer_user: User,
    mechanic_profile: MechanicProfile,
):
    """Webhook: charge.refund.created logs the refund."""
    booking = _make_booking(buyer_user.id, mechanic_profile.id, status=BookingStatus.CANCELLED)
    db.add(booking)
    await db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "charge.refund.created",
        "data": {
            "object": {
                "id": "re_test_123",
                "payment_intent": booking.stripe_payment_intent_id,
                "amount": 5000,
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_webhook_succeeded_no_matching_booking(
    client: AsyncClient,
    db: AsyncSession,
):
    """Webhook: payment_intent.succeeded with no matching booking still returns ok."""
    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "payment_intent.succeeded",
        "data": {
            "object": {
                "id": "pi_nonexistent",
            }
        },
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        response = await client.post(
            "/payments/webhooks/stripe",
            content=b"{}",
            headers={"stripe-signature": "test_sig"},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ============ Content-Length validation ============


@pytest.mark.asyncio
async def test_webhook_payload_too_large_header(client: AsyncClient):
    """Reject webhook when Content-Length exceeds 64KB."""
    resp = await client.post(
        "/payments/webhooks/stripe",
        content=b"x",
        headers={"stripe-signature": "t=123,v1=abc", "content-length": "100000"},
    )
    assert resp.status_code == 413


@pytest.mark.asyncio
async def test_webhook_invalid_content_length(client: AsyncClient):
    """Reject webhook with non-numeric Content-Length."""
    resp = await client.post(
        "/payments/webhooks/stripe",
        content=b"x",
        headers={"stripe-signature": "t=123,v1=abc", "content-length": "not_a_number"},
    )
    assert resp.status_code == 400


# ============ account.updated ============


@pytest_asyncio.fixture
async def pay2_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with TestSessionFactory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def pay2_client(pay2_db):
    async def override_get_db():
        yield pay2_db
    app.dependency_overrides[get_db] = override_get_db
    from app.utils.rate_limit import limiter
    if hasattr(limiter, "_limiter") and hasattr(limiter._limiter, "_storage"):
        limiter._limiter._storage.reset()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


def _post_webhook_event(event):
    """Build kwargs for posting a webhook event."""
    import json
    payload = json.dumps(event).encode()
    return {
        "content": payload,
        "headers": {"stripe-signature": "t=123,v1=abc", "content-length": str(len(payload))},
    }


@pytest.mark.asyncio
async def test_webhook_account_updated_fully_onboarded(pay2_client, pay2_db):
    """account.updated activates verified mechanic profile."""
    mech = User(
        id=uuid.uuid4(), email="au_mech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC, phone="+33600000050", is_verified=True,
    )
    pay2_db.add(mech)
    await pay2_db.flush()

    profile = MechanicProfile(
        id=uuid.uuid4(), user_id=mech.id, city="Bordeaux",
        city_lat=44.84, city_lng=-0.57, max_radius_km=30,
        free_zone_km=5, accepted_vehicle_types=["car"],
        is_identity_verified=True, is_active=False,
        stripe_account_id="acct_onboard_test",
    )
    pay2_db.add(profile)
    await pay2_db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "account.updated",
        "data": {"object": {"id": "acct_onboard_test", "charges_enabled": True, "payouts_enabled": True}},
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        resp = await pay2_client.post("/payments/webhooks/stripe", **_post_webhook_event(event))

    assert resp.status_code == 200
    await pay2_db.refresh(profile)
    assert profile.is_active is True


@pytest.mark.asyncio
async def test_webhook_account_updated_not_verified(pay2_client, pay2_db):
    """account.updated does NOT activate if identity not verified."""
    mech = User(
        id=uuid.uuid4(), email="au_mech2@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC, phone="+33600000051", is_verified=True,
    )
    pay2_db.add(mech)
    await pay2_db.flush()

    profile = MechanicProfile(
        id=uuid.uuid4(), user_id=mech.id, city="Nantes",
        city_lat=47.22, city_lng=-1.55, max_radius_km=30,
        free_zone_km=5, accepted_vehicle_types=["car"],
        is_identity_verified=False, is_active=False,
        stripe_account_id="acct_noverify",
    )
    pay2_db.add(profile)
    await pay2_db.flush()

    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "account.updated",
        "data": {"object": {"id": "acct_noverify", "charges_enabled": True, "payouts_enabled": True}},
    }

    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        resp = await pay2_client.post("/payments/webhooks/stripe", **_post_webhook_event(event))

    assert resp.status_code == 200
    await pay2_db.refresh(profile)
    assert profile.is_active is False


@pytest.mark.asyncio
async def test_webhook_account_updated_partial(pay2_client, pay2_db):
    """account.updated with partial onboarding doesn't activate."""
    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "account.updated",
        "data": {"object": {"id": "acct_partial", "charges_enabled": True, "payouts_enabled": False}},
    }
    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        resp = await pay2_client.post("/payments/webhooks/stripe", **_post_webhook_event(event))
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_webhook_account_updated_no_profile(pay2_client, pay2_db):
    """account.updated for unknown account logs warning."""
    event = {
        "id": f"evt_{uuid.uuid4().hex[:16]}",
        "type": "account.updated",
        "data": {"object": {"id": "acct_unknown", "charges_enabled": True, "payouts_enabled": True}},
    }
    with patch("app.payments.routes.verify_webhook_signature", return_value=event):
        resp = await pay2_client.post("/payments/webhooks/stripe", **_post_webhook_event(event))
    assert resp.status_code == 200


# ============ Dispute resolution ============


@pytest.mark.asyncio
async def test_resolve_dispute_buyer(pay2_client, pay2_db):
    """Admin resolves dispute in favor of buyer (refund)."""
    admin = User(
        id=uuid.uuid4(), email="admin_dr@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN, phone="+33600000070", is_verified=True,
    )
    buyer = User(
        id=uuid.uuid4(), email="dr_buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000071", is_verified=True,
    )
    mech = User(
        id=uuid.uuid4(), email="dr_mech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC, phone="+33600000072", is_verified=True,
    )
    pay2_db.add_all([admin, buyer, mech])
    await pay2_db.flush()

    profile = MechanicProfile(
        id=uuid.uuid4(), user_id=mech.id, city="Nice",
        city_lat=43.71, city_lng=7.26, max_radius_km=30,
        free_zone_km=5, accepted_vehicle_types=["car"],
        is_identity_verified=True, is_active=True, no_show_count=0,
    )
    pay2_db.add(profile)
    await pay2_db.flush()

    booking = Booking(
        id=uuid.uuid4(), buyer_id=buyer.id, mechanic_id=profile.id,
        status=BookingStatus.DISPUTED,
        vehicle_type=VehicleType.CAR, vehicle_brand="Test", vehicle_model="DR",
        vehicle_year=2020, meeting_address="Addr DR", meeting_lat=43.71, meeting_lng=7.26,
        distance_km=2, base_price=Decimal("89.00"), travel_fees=Decimal("0.00"),
        total_price=Decimal("89.00"), commission_rate=Decimal("0.15"),
        commission_amount=Decimal("13.35"), mechanic_payout=Decimal("75.65"),
        stripe_payment_intent_id="pi_mock_8900",
    )
    pay2_db.add(booking)
    await pay2_db.flush()

    dispute = DisputeCase(
        id=uuid.uuid4(), booking_id=booking.id,
        opened_by=buyer.id, reason=DisputeReason.NO_SHOW,
        description="Mechanic did not show up", status=DisputeStatus.OPEN,
    )
    pay2_db.add(dispute)
    await pay2_db.flush()

    token = create_access_token(str(admin.id))
    resp = await pay2_client.patch(
        "/payments/disputes/resolve",
        json={"dispute_id": str(dispute.id), "resolution": "buyer", "resolution_notes": "No-show confirmed"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    assert resp.json()["resolution"] == "buyer"
    await pay2_db.refresh(booking)
    assert booking.status == BookingStatus.CANCELLED


@pytest.mark.asyncio
async def test_resolve_dispute_mechanic(pay2_client, pay2_db):
    """Admin resolves dispute in favor of mechanic (release payment)."""
    admin = User(
        id=uuid.uuid4(), email="admin_drm@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN, phone="+33600000080", is_verified=True,
    )
    buyer = User(
        id=uuid.uuid4(), email="drm_buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000081", is_verified=True,
    )
    mech = User(
        id=uuid.uuid4(), email="drm_mech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC, phone="+33600000082", is_verified=True,
    )
    pay2_db.add_all([admin, buyer, mech])
    await pay2_db.flush()

    profile = MechanicProfile(
        id=uuid.uuid4(), user_id=mech.id, city="Lille",
        city_lat=50.63, city_lng=3.06, max_radius_km=30,
        free_zone_km=5, accepted_vehicle_types=["car"],
        is_identity_verified=True, is_active=True,
    )
    pay2_db.add(profile)
    await pay2_db.flush()

    booking = Booking(
        id=uuid.uuid4(), buyer_id=buyer.id, mechanic_id=profile.id,
        status=BookingStatus.DISPUTED,
        vehicle_type=VehicleType.CAR, vehicle_brand="Test", vehicle_model="DRM",
        vehicle_year=2022, meeting_address="Addr DRM", meeting_lat=50.63, meeting_lng=3.06,
        distance_km=3, base_price=Decimal("89.00"), travel_fees=Decimal("5.00"),
        total_price=Decimal("94.00"), commission_rate=Decimal("0.15"),
        commission_amount=Decimal("14.10"), mechanic_payout=Decimal("79.90"),
        stripe_payment_intent_id="pi_mock_9400",
    )
    pay2_db.add(booking)
    await pay2_db.flush()

    dispute = DisputeCase(
        id=uuid.uuid4(), booking_id=booking.id,
        opened_by=buyer.id, reason=DisputeReason.WRONG_INFO,
        description="Buyer claims wrong info", status=DisputeStatus.OPEN,
    )
    pay2_db.add(dispute)
    await pay2_db.flush()

    token = create_access_token(str(admin.id))
    resp = await pay2_client.patch(
        "/payments/disputes/resolve",
        json={"dispute_id": str(dispute.id), "resolution": "mechanic", "resolution_notes": "Info was correct"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert resp.status_code == 200
    await pay2_db.refresh(booking)
    assert booking.status == BookingStatus.COMPLETED
    assert booking.payment_released_at is not None


@pytest.mark.asyncio
async def test_resolve_dispute_not_found(pay2_client, pay2_db):
    """Resolving non-existent dispute returns 404."""
    admin = User(
        id=uuid.uuid4(), email="admin_nf@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN, phone="+33600000090", is_verified=True,
    )
    pay2_db.add(admin)
    await pay2_db.flush()

    token = create_access_token(str(admin.id))
    resp = await pay2_client.patch(
        "/payments/disputes/resolve",
        json={"dispute_id": str(uuid.uuid4()), "resolution": "buyer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_resolve_dispute_already_resolved(pay2_client, pay2_db):
    """Resolving already-resolved dispute returns 409."""
    admin = User(
        id=uuid.uuid4(), email="admin_ar@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.ADMIN, phone="+33600000091", is_verified=True,
    )
    buyer = User(
        id=uuid.uuid4(), email="ar_buyer@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.BUYER, phone="+33600000092", is_verified=True,
    )
    mech = User(
        id=uuid.uuid4(), email="ar_mech@test.com",
        password_hash=hash_password("password123"),
        role=UserRole.MECHANIC, phone="+33600000093", is_verified=True,
    )
    pay2_db.add_all([admin, buyer, mech])
    await pay2_db.flush()

    profile = MechanicProfile(
        id=uuid.uuid4(), user_id=mech.id, city="Rennes",
        city_lat=48.11, city_lng=-1.68, max_radius_km=30,
        free_zone_km=5, accepted_vehicle_types=["car"],
        is_identity_verified=True, is_active=True,
    )
    pay2_db.add(profile)
    await pay2_db.flush()

    booking = Booking(
        id=uuid.uuid4(), buyer_id=buyer.id, mechanic_id=profile.id,
        status=BookingStatus.CANCELLED,
        vehicle_type=VehicleType.CAR, vehicle_brand="Test", vehicle_model="AR",
        vehicle_year=2020, meeting_address="Addr AR", meeting_lat=48.11, meeting_lng=-1.68,
        distance_km=1, base_price=Decimal("89.00"), travel_fees=Decimal("0.00"),
        total_price=Decimal("89.00"), commission_rate=Decimal("0.15"),
        commission_amount=Decimal("13.35"), mechanic_payout=Decimal("75.65"),
    )
    pay2_db.add(booking)
    await pay2_db.flush()

    dispute = DisputeCase(
        id=uuid.uuid4(), booking_id=booking.id,
        opened_by=buyer.id, reason=DisputeReason.OTHER,
        description="Already resolved", status=DisputeStatus.RESOLVED_BUYER,
    )
    pay2_db.add(dispute)
    await pay2_db.flush()

    token = create_access_token(str(admin.id))
    resp = await pay2_client.patch(
        "/payments/disputes/resolve",
        json={"dispute_id": str(dispute.id), "resolution": "buyer"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 409
