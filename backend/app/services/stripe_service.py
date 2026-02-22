import asyncio
import json  # Used in dev mode for mock webhook payload parsing (verify_webhook_signature)
import time as _time

import stripe
import structlog
from fastapi import HTTPException

from app.config import settings
from app.metrics import STRIPE_CALL_DURATION


class StripeServiceError(Exception):
    """Exception raised when Stripe operations fail.

    PAY-R01: Use this instead of HTTPException so that non-HTTP callers
    (e.g., scheduler jobs) get a clean exception without HTTP semantics.
    """

logger = structlog.get_logger()


async def create_payment_intent(
    amount_cents: int,
    mechanic_stripe_account_id: str | None,
    commission_cents: int,
    metadata: dict[str, str] | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Create a Stripe PaymentIntent with platform fee.

    Returns dict with 'id' and 'client_secret'.
    """
    if not settings.STRIPE_SECRET_KEY:
        # No Stripe key at all: full mock mode
        logger.info("stripe_mock_payment_intent", amount=amount_cents)
        return {
            "id": f"pi_mock_{amount_cents}",
            "client_secret": None,
        }

    is_mock_account = mechanic_stripe_account_id and mechanic_stripe_account_id.startswith("acct_mock_")

    params: dict = {
        "amount": amount_cents,
        "currency": "eur",
        "capture_method": "manual",  # Hold funds, capture later
        "metadata": metadata or {},
        "api_key": settings.STRIPE_SECRET_KEY,
    }

    # Only add Connect transfer for real Stripe accounts
    if mechanic_stripe_account_id and not is_mock_account:
        params["transfer_data"] = {"destination": mechanic_stripe_account_id}
        params["application_fee_amount"] = commission_cents

    # LOW-03: Pass idempotency key to prevent duplicate charges on retries
    create_kwargs: dict = {**params}
    if idempotency_key:
        create_kwargs["idempotency_key"] = idempotency_key

    start = _time.monotonic()
    intent = await asyncio.wait_for(
        asyncio.to_thread(stripe.PaymentIntent.create, **create_kwargs), timeout=15.0
    )
    STRIPE_CALL_DURATION.labels(operation="create_payment_intent").observe(_time.monotonic() - start)
    logger.info("stripe_payment_intent_created", intent_id=intent.id)
    return {"id": intent.id, "client_secret": intent.client_secret}


async def cancel_payment_intent(payment_intent_id: str, idempotency_key: str | None = None) -> None:
    """Cancel an uncaptured PaymentIntent, or refund if already captured."""
    if not settings.STRIPE_SECRET_KEY or payment_intent_id.startswith("pi_mock_"):
        logger.info("stripe_mock_cancel", intent_id=payment_intent_id)
        return

    try:
        intent = await asyncio.wait_for(
            asyncio.to_thread(stripe.PaymentIntent.retrieve, payment_intent_id, api_key=settings.STRIPE_SECRET_KEY), timeout=15.0
        )
        if intent.status == "canceled":
            logger.info("stripe_payment_intent_already_cancelled", intent_id=payment_intent_id)
            return
        if intent.status == "succeeded":
            # Already captured -- create a refund instead
            refund_params = {"payment_intent": payment_intent_id, "api_key": settings.STRIPE_SECRET_KEY}
            if idempotency_key:
                refund_params["idempotency_key"] = f"fullrefund_{idempotency_key}"
            await asyncio.wait_for(asyncio.to_thread(stripe.Refund.create, **refund_params), timeout=15.0)
            logger.info("stripe_payment_refunded", intent_id=payment_intent_id)
        elif intent.status == "processing":
            logger.warning("stripe_cancel_skipped_processing", intent_id=payment_intent_id)
            raise stripe.StripeError(f"PaymentIntent {payment_intent_id} is still processing")
        else:
            cancel_params = {"api_key": settings.STRIPE_SECRET_KEY}
            if idempotency_key:
                cancel_params["idempotency_key"] = idempotency_key
            await asyncio.wait_for(asyncio.to_thread(stripe.PaymentIntent.cancel, payment_intent_id, **cancel_params), timeout=15.0)
            logger.info("stripe_payment_intent_cancelled", intent_id=payment_intent_id)
    except stripe.StripeError as e:
        logger.exception("stripe_cancel_failed", intent_id=payment_intent_id)
        raise StripeServiceError(f"Stripe cancellation failed: {e}") from None


async def refund_payment_intent(
    payment_intent_id: str,
    amount_cents: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    """Refund a captured PaymentIntent, or cancel if not yet captured."""
    if not settings.STRIPE_SECRET_KEY or payment_intent_id.startswith("pi_mock_"):
        logger.info("stripe_mock_refund", intent_id=payment_intent_id, amount=amount_cents)
        return {"id": f"re_mock_{payment_intent_id}", "status": "succeeded"}

    # PAY-22: Check PI status — cancel (release hold) if not captured
    intent = await asyncio.wait_for(
        asyncio.to_thread(
            stripe.PaymentIntent.retrieve, payment_intent_id, api_key=settings.STRIPE_SECRET_KEY
        ),
        timeout=15.0,
    )
    if intent.status != "succeeded":
        logger.info("stripe_refund_as_cancel", intent_id=payment_intent_id, status=intent.status)
        cancel_params: dict = {"api_key": settings.STRIPE_SECRET_KEY}
        if idempotency_key:
            cancel_params["idempotency_key"] = f"cancel_{idempotency_key}"
        canceled = await asyncio.wait_for(
            asyncio.to_thread(stripe.PaymentIntent.cancel, payment_intent_id, **cancel_params),
            timeout=15.0,
        )
        return {"id": canceled.id, "status": "canceled"}

    # PAY-19: Validate refund amount doesn't exceed what's refundable
    if amount_cents is not None:
        max_refundable = intent.amount - (intent.amount_refunded or 0)
        if amount_cents > max_refundable:
            raise ValueError(f"Refund amount {amount_cents} exceeds max refundable {max_refundable}")

    params: dict = {"payment_intent": payment_intent_id, "api_key": settings.STRIPE_SECRET_KEY}
    if amount_cents is not None:
        params["amount"] = amount_cents
    if idempotency_key:
        params["idempotency_key"] = idempotency_key

    refund = await asyncio.wait_for(
        asyncio.to_thread(stripe.Refund.create, **params), timeout=15.0
    )
    logger.info("stripe_refund_created", refund_id=refund.id, intent_id=payment_intent_id)
    return {"id": refund.id, "status": refund.status}


async def capture_payment_intent(payment_intent_id: str, idempotency_key: str | None = None) -> None:
    """Capture a previously authorized PaymentIntent (release funds to mechanic).

    AUD4-002: Retrieve the PI first and check its status to avoid capturing
    an already-captured, canceled, or processing PaymentIntent.
    """
    if not settings.STRIPE_SECRET_KEY or payment_intent_id.startswith("pi_mock_"):
        logger.info("stripe_mock_capture", intent_id=payment_intent_id)
        return

    try:
        # Retrieve PI to check status before attempting capture
        start = _time.monotonic()
        intent = await asyncio.wait_for(
            asyncio.to_thread(
                stripe.PaymentIntent.retrieve,
                payment_intent_id,
                api_key=settings.STRIPE_SECRET_KEY,
            ),
            timeout=15.0,
        )

        if intent.status == "succeeded":
            logger.info("stripe_payment_already_captured", intent_id=payment_intent_id)
            return

        if intent.status != "requires_capture":
            logger.warning(
                "stripe_capture_unexpected_status",
                intent_id=payment_intent_id,
                status=intent.status,
            )
            return

        capture_params = {"api_key": settings.STRIPE_SECRET_KEY}
        if idempotency_key:
            capture_params["idempotency_key"] = idempotency_key
        await asyncio.wait_for(
            asyncio.to_thread(stripe.PaymentIntent.capture, payment_intent_id, **capture_params), timeout=15.0
        )
        STRIPE_CALL_DURATION.labels(operation="capture_payment_intent").observe(_time.monotonic() - start)
        logger.info("stripe_payment_intent_captured", intent_id=payment_intent_id)
    except stripe.StripeError as e:
        logger.exception("stripe_capture_failed", intent_id=payment_intent_id)
        raise StripeServiceError(f"Stripe capture failed: {e}") from None


async def create_connect_account(email: str) -> dict:
    """Create a Stripe Connect Express account for a mechanic."""
    if not settings.STRIPE_SECRET_KEY:
        logger.info("stripe_mock_connect_account", email=email)
        return {
            "account_id": "acct_mock_123",
            "onboarding_url": "https://connect.stripe.com/mock-onboarding",
        }

    account = await asyncio.wait_for(
        asyncio.to_thread(
            stripe.Account.create,
            type="express",
            country="FR",
            email=email,
            capabilities={"card_payments": {"requested": True}, "transfers": {"requested": True}},
            api_key=settings.STRIPE_SECRET_KEY,
        ),
        timeout=15.0,
    )

    account_link = await asyncio.wait_for(
        asyncio.to_thread(
            stripe.AccountLink.create,
            account=account.id,
            refresh_url=settings.STRIPE_REFRESH_URL,
            return_url=settings.STRIPE_RETURN_URL,
            type="account_onboarding",
            api_key=settings.STRIPE_SECRET_KEY,
        ),
        timeout=15.0,
    )

    logger.info("stripe_connect_account_created", account_id=account.id)
    return {"account_id": account.id, "onboarding_url": account_link.url}


async def create_login_link(stripe_account_id: str) -> str:
    """Create a Stripe Express Dashboard login link."""
    if not settings.STRIPE_SECRET_KEY or stripe_account_id.startswith("acct_mock_"):
        return "https://connect.stripe.com/mock-dashboard"

    link = await asyncio.wait_for(
        asyncio.to_thread(stripe.Account.create_login_link, stripe_account_id, api_key=settings.STRIPE_SECRET_KEY), timeout=15.0
    )
    return link.url


def verify_webhook_signature(payload: bytes, sig_header: str) -> stripe.Event:
    """Verify Stripe webhook signature and return the event."""
    # SEC-008: Reject placeholder webhook secrets in production/staging
    if (
        settings.APP_ENV in ("production", "staging")
        and settings.STRIPE_WEBHOOK_SECRET.startswith("whsec_PLACEHOLDER")
    ):
        logger.warning("stripe_webhook_placeholder_secret_detected")
        raise HTTPException(status_code=500, detail="Webhook verification not configured")

    # SEC-001: Reject webhooks when no secret is configured, even in dev mode.
    # This prevents forged webhook events from bypassing signature verification.
    if not settings.STRIPE_WEBHOOK_SECRET:
        logger.error("stripe_webhook_rejected_no_secret")
        raise HTTPException(
            status_code=501,
            detail="Webhook signature verification not configured",
        )

    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET, api_key=settings.STRIPE_SECRET_KEY
    )
