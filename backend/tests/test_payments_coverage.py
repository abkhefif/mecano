import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.booking import Booking
from app.models.enums import BookingStatus, DisputeReason, DisputeStatus, UserRole, VehicleType
from app.models.dispute import DisputeCase
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.models.webhook_event import ProcessedWebhookEvent
from tests.conftest import auth_header, buyer_token, mechanic_token


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
