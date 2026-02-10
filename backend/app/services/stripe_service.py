import asyncio

import stripe
import structlog

from app.config import settings

logger = structlog.get_logger()

stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_payment_intent(
    amount_cents: int,
    mechanic_stripe_account_id: str | None,
    commission_cents: int,
    metadata: dict | None = None,
) -> dict:
    """Create a Stripe PaymentIntent with platform fee.

    Returns dict with 'id' and 'client_secret'.
    """
    if not settings.STRIPE_SECRET_KEY:
        # Development mode: return mock
        logger.info("stripe_mock_payment_intent", amount=amount_cents)
        return {
            "id": f"pi_mock_{amount_cents}",
            "client_secret": f"pi_mock_{amount_cents}_secret_mock",
        }

    params: dict = {
        "amount": amount_cents,
        "currency": "eur",
        "capture_method": "manual",  # Hold funds, capture later
        "metadata": metadata or {},
    }

    if mechanic_stripe_account_id:
        params["transfer_data"] = {"destination": mechanic_stripe_account_id}
        params["application_fee_amount"] = commission_cents

    intent = await asyncio.to_thread(stripe.PaymentIntent.create, **params)
    logger.info("stripe_payment_intent_created", intent_id=intent.id)
    return {"id": intent.id, "client_secret": intent.client_secret}


async def cancel_payment_intent(payment_intent_id: str) -> None:
    """Cancel an uncaptured PaymentIntent, or refund if already captured."""
    if not settings.STRIPE_SECRET_KEY or payment_intent_id.startswith("pi_mock_"):
        logger.info("stripe_mock_cancel", intent_id=payment_intent_id)
        return

    try:
        intent = await asyncio.to_thread(stripe.PaymentIntent.retrieve, payment_intent_id)
        if intent.status == "canceled":
            logger.info("stripe_payment_intent_already_cancelled", intent_id=payment_intent_id)
            return
        if intent.status == "succeeded":
            # Already captured -- create a refund instead
            await asyncio.to_thread(stripe.Refund.create, payment_intent=payment_intent_id)
            logger.info("stripe_payment_refunded", intent_id=payment_intent_id)
        elif intent.status == "processing":
            logger.warning("stripe_cancel_skipped_processing", intent_id=payment_intent_id)
            raise stripe.StripeError(f"PaymentIntent {payment_intent_id} is still processing")
        else:
            await asyncio.to_thread(stripe.PaymentIntent.cancel, payment_intent_id)
            logger.info("stripe_payment_intent_cancelled", intent_id=payment_intent_id)
    except stripe.StripeError:
        logger.exception("stripe_cancel_failed", intent_id=payment_intent_id)
        raise


async def capture_payment_intent(payment_intent_id: str) -> None:
    """Capture a previously authorized PaymentIntent (release funds to mechanic)."""
    if not settings.STRIPE_SECRET_KEY or payment_intent_id.startswith("pi_mock_"):
        logger.info("stripe_mock_capture", intent_id=payment_intent_id)
        return

    try:
        await asyncio.to_thread(stripe.PaymentIntent.capture, payment_intent_id)
        logger.info("stripe_payment_intent_captured", intent_id=payment_intent_id)
    except stripe.StripeError:
        logger.exception("stripe_capture_failed", intent_id=payment_intent_id)
        raise


async def create_connect_account(email: str) -> dict:
    """Create a Stripe Connect Express account for a mechanic."""
    if not settings.STRIPE_SECRET_KEY:
        logger.info("stripe_mock_connect_account", email=email)
        return {
            "account_id": "acct_mock_123",
            "onboarding_url": "https://connect.stripe.com/mock-onboarding",
        }

    account = await asyncio.to_thread(
        stripe.Account.create,
        type="express",
        country="FR",
        email=email,
        capabilities={"card_payments": {"requested": True}, "transfers": {"requested": True}},
    )

    account_link = await asyncio.to_thread(
        stripe.AccountLink.create,
        account=account.id,
        refresh_url=settings.STRIPE_REFRESH_URL,
        return_url=settings.STRIPE_RETURN_URL,
        type="account_onboarding",
    )

    logger.info("stripe_connect_account_created", account_id=account.id)
    return {"account_id": account.id, "onboarding_url": account_link.url}


async def create_login_link(stripe_account_id: str) -> str:
    """Create a Stripe Express Dashboard login link."""
    if not settings.STRIPE_SECRET_KEY or stripe_account_id.startswith("acct_mock_"):
        return "https://connect.stripe.com/mock-dashboard"

    link = await asyncio.to_thread(stripe.Account.create_login_link, stripe_account_id)
    return link.url


def verify_webhook_signature(payload: bytes, sig_header: str) -> dict:
    """Verify Stripe webhook signature and return the event."""
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
