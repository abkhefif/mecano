"""Coverage tests for stripe_service.py — targeting uncovered lines.

Tests the real Stripe code paths (cancel status flows, refund logic,
capture with idempotency, webhook signature verification).
"""
import asyncio
from unittest.mock import MagicMock, patch

import pytest
import stripe
from fastapi import HTTPException

from app.services.stripe_service import (
    cancel_payment_intent,
    capture_payment_intent,
    create_payment_intent,
    refund_payment_intent,
    verify_webhook_signature,
)


# ============ create_payment_intent ============


@pytest.mark.asyncio
async def test_create_payment_intent_with_idempotency_key():
    """Idempotency key is forwarded to stripe.PaymentIntent.create."""
    mock_intent = MagicMock(id="pi_test_123", client_secret="sec_test")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:
            result = await create_payment_intent(
                amount_cents=5000,
                mechanic_stripe_account_id=None,
                commission_cents=500,
                idempotency_key="idem_123",
            )

    assert result["id"] == "pi_test_123"
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["idempotency_key"] == "idem_123"


@pytest.mark.asyncio
async def test_create_payment_intent_with_real_connect_account():
    """Transfer data is added for real (non-mock) Stripe accounts."""
    mock_intent = MagicMock(id="pi_real", client_secret="sec_real")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.create", return_value=mock_intent) as mock_create:
            result = await create_payment_intent(
                amount_cents=10000,
                mechanic_stripe_account_id="acct_real_456",
                commission_cents=1000,
            )

    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["transfer_data"] == {"destination": "acct_real_456"}
    assert call_kwargs["application_fee_amount"] == 1000


# ============ cancel_payment_intent ============


@pytest.mark.asyncio
async def test_cancel_already_cancelled():
    """No-op when intent is already canceled."""
    mock_intent = MagicMock(status="canceled")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.Refund.create") as mock_refund, \
             patch("stripe.PaymentIntent.cancel") as mock_cancel:
            await cancel_payment_intent("pi_test_456")

    mock_refund.assert_not_called()
    mock_cancel.assert_not_called()


@pytest.mark.asyncio
async def test_cancel_succeeded_creates_refund():
    """Succeeded intent triggers a refund instead of cancel."""
    mock_intent = MagicMock(status="succeeded")
    mock_refund_obj = MagicMock()

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.Refund.create", return_value=mock_refund_obj) as mock_refund:
            await cancel_payment_intent("pi_test_789", idempotency_key="key1")

    call_kwargs = mock_refund.call_args[1]
    assert call_kwargs["payment_intent"] == "pi_test_789"
    assert call_kwargs["idempotency_key"] == "fullrefund_key1"


@pytest.mark.asyncio
async def test_cancel_processing_raises():
    """Processing intent raises StripeServiceError."""
    from app.services.stripe_service import StripeServiceError

    mock_intent = MagicMock(status="processing")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent):
            with pytest.raises(StripeServiceError):
                await cancel_payment_intent("pi_processing")


@pytest.mark.asyncio
async def test_cancel_requires_capture_does_cancel():
    """Normal cancel path for requires_capture status."""
    mock_intent = MagicMock(status="requires_capture")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.PaymentIntent.cancel") as mock_cancel:
            await cancel_payment_intent("pi_cancel_me", idempotency_key="key2")

    mock_cancel.assert_called_once()
    call_args = mock_cancel.call_args
    assert call_args[0][0] == "pi_cancel_me"
    assert call_args[1]["idempotency_key"] == "key2"


@pytest.mark.asyncio
async def test_cancel_stripe_error_raises_service_error():
    """StripeError during cancel raises StripeServiceError."""
    from app.services.stripe_service import StripeServiceError

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", side_effect=stripe.StripeError("fail")):
            with pytest.raises(StripeServiceError):
                await cancel_payment_intent("pi_err")


# ============ refund_payment_intent ============


@pytest.mark.asyncio
async def test_refund_not_succeeded_cancels_instead():
    """Non-succeeded intent is canceled, not refunded."""
    mock_intent = MagicMock(status="requires_capture", id="pi_cancel")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.PaymentIntent.cancel", return_value=MagicMock(id="pi_cancel", status="canceled")) as mock_cancel:
            result = await refund_payment_intent("pi_cancel", idempotency_key="k1")

    assert result["status"] == "canceled"
    call_kwargs = mock_cancel.call_args[1]
    assert call_kwargs["idempotency_key"] == "cancel_k1"


@pytest.mark.asyncio
async def test_refund_amount_exceeds_max():
    """ValueError when refund amount exceeds max refundable."""
    mock_intent = MagicMock(status="succeeded", amount=10000, amount_refunded=8000)

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent):
            with pytest.raises(ValueError, match="exceeds max refundable"):
                await refund_payment_intent("pi_over", amount_cents=5000)


@pytest.mark.asyncio
async def test_refund_partial_amount():
    """Partial refund passes amount to Stripe."""
    mock_intent = MagicMock(status="succeeded", amount=10000, amount_refunded=0)
    mock_refund = MagicMock(id="re_partial", status="succeeded")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.Refund.create", return_value=mock_refund) as mock_create:
            result = await refund_payment_intent("pi_partial", amount_cents=3000, idempotency_key="rk1")

    assert result["id"] == "re_partial"
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["amount"] == 3000
    assert call_kwargs["idempotency_key"] == "rk1"


@pytest.mark.asyncio
async def test_refund_full_no_amount():
    """Full refund (no amount specified) creates a full Stripe refund."""
    mock_intent = MagicMock(status="succeeded", amount=5000, amount_refunded=0)
    mock_refund = MagicMock(id="re_full", status="succeeded")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.Refund.create", return_value=mock_refund) as mock_create:
            result = await refund_payment_intent("pi_full")

    assert result["id"] == "re_full"
    call_kwargs = mock_create.call_args[1]
    assert "amount" not in call_kwargs


# ============ capture_payment_intent ============


@pytest.mark.asyncio
async def test_capture_already_succeeded():
    """No-op when intent is already captured (succeeded)."""
    mock_intent = MagicMock(status="succeeded")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.PaymentIntent.capture") as mock_capture:
            await capture_payment_intent("pi_captured")

    mock_capture.assert_not_called()


@pytest.mark.asyncio
async def test_capture_unexpected_status():
    """No-op when intent has unexpected status (e.g. canceled)."""
    mock_intent = MagicMock(status="canceled")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.PaymentIntent.capture") as mock_capture:
            await capture_payment_intent("pi_unexpected")

    mock_capture.assert_not_called()


@pytest.mark.asyncio
async def test_capture_requires_capture_with_idempotency():
    """Normal capture path with idempotency key."""
    mock_intent = MagicMock(status="requires_capture")

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", return_value=mock_intent), \
             patch("stripe.PaymentIntent.capture") as mock_capture:
            await capture_payment_intent("pi_cap", idempotency_key="cap_key")

    mock_capture.assert_called_once()
    call_kwargs = mock_capture.call_args[1]
    assert call_kwargs["idempotency_key"] == "cap_key"


@pytest.mark.asyncio
async def test_capture_stripe_error_raises_service_error():
    """StripeError during capture raises StripeServiceError."""
    from app.services.stripe_service import StripeServiceError

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_SECRET_KEY = "sk_test_123"
        with patch("stripe.PaymentIntent.retrieve", side_effect=stripe.StripeError("fail")):
            with pytest.raises(StripeServiceError):
                await capture_payment_intent("pi_err_cap")


# ============ verify_webhook_signature ============


def test_webhook_placeholder_secret_rejected_in_any_env():
    """Reject placeholder webhook secret in ALL environments."""
    for env in ("production", "staging", "development"):
        with patch("app.services.stripe_service.settings") as mock_s:
            mock_s.STRIPE_WEBHOOK_SECRET = "whsec_PLACEHOLDER_test"
            with pytest.raises(HTTPException) as exc_info:
                verify_webhook_signature(b"payload", "sig")
        assert exc_info.value.status_code == 400


def test_webhook_no_secret_configured():
    """Reject webhooks when no secret is set at all."""
    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.STRIPE_WEBHOOK_SECRET = ""
        with pytest.raises(HTTPException) as exc_info:
            verify_webhook_signature(b"payload", "sig")
    assert exc_info.value.status_code == 400


def test_webhook_valid_secret_calls_construct_event():
    """Valid secret delegates to stripe.Webhook.construct_event."""
    mock_event = {"id": "evt_123", "type": "payment_intent.succeeded"}

    with patch("app.services.stripe_service.settings") as mock_s:
        mock_s.APP_ENV = "development"
        mock_s.STRIPE_WEBHOOK_SECRET = "whsec_real_secret"
        mock_s.STRIPE_SECRET_KEY = "sk_test"
        with patch("stripe.Webhook.construct_event", return_value=mock_event) as mock_construct:
            result = verify_webhook_signature(b"payload", "sig_header")

    assert result == mock_event
    mock_construct.assert_called_once_with(b"payload", "sig_header", "whsec_real_secret", api_key="sk_test")
