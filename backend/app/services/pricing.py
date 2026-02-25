from decimal import ROUND_HALF_UP, Decimal

from app.config import settings


def calculate_travel_fees(distance_km: float, free_zone_km: int) -> Decimal:
    """Calculate travel fees based on distance beyond the free zone."""
    billable_km = max(0, distance_km - free_zone_km)
    return (Decimal(str(billable_km)) * settings.TRAVEL_FEE_PER_KM).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def calculate_stripe_fee(amount: Decimal) -> Decimal:
    """Calculate Stripe processing fee for EEA premium cards (1.9% + 0.25€).

    Uses the highest EEA rate (premium cards) to guarantee that the platform
    and mechanic always receive their full amounts regardless of card type.
    With standard cards (1.5%), the small surplus stays on the platform.

    Formula: charge = (amount + 0.25) / (1 - 0.019)
    The fee is: charge - amount
    """
    stripe_percent = Decimal("0.019")  # 1.9% (EEA premium — worst case France)
    stripe_fixed = Decimal("0.25")     # 0.25€ fixed fee
    charge_amount = ((amount + stripe_fixed) / (1 - stripe_percent)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return (charge_amount - amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def calculate_booking_pricing(
    distance_km: float, free_zone_km: int, obd_requested: bool = False
) -> dict[str, Decimal]:
    """Calculate full booking pricing breakdown.

    Goal: the mechanic receives exactly `mechanic_payout` net.
    The buyer pays: mechanic_payout + platform_commission + stripe_fee.

    Flow on Stripe Connect:
      - Buyer is charged `total_price`
      - Stripe takes ~1.5% + 0.25€
      - application_fee_amount = commission_amount (goes to eMecano)
      - The rest (transfer) goes to mechanic's Stripe account
    """
    base_price = settings.BASE_INSPECTION_PRICE
    if obd_requested:
        base_price = base_price + settings.OBD_SUPPLEMENT
    travel_fees = calculate_travel_fees(distance_km, free_zone_km)

    # mechanic_payout = what the mechanic receives net
    mechanic_payout = base_price + travel_fees

    # Platform commission = 20% of mechanic_payout
    commission_rate = settings.PLATFORM_COMMISSION_RATE
    commission_amount = (mechanic_payout * commission_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Subtotal before Stripe fees = what must arrive on Stripe
    subtotal = mechanic_payout + commission_amount

    # Stripe fee on top so buyer absorbs it
    stripe_fee = calculate_stripe_fee(subtotal)
    total_price = subtotal + stripe_fee

    return {
        "base_price": base_price,
        "travel_fees": travel_fees,
        "stripe_fee": stripe_fee,
        "total_price": total_price,
        "commission_rate": commission_rate,
        "commission_amount": commission_amount,
        "mechanic_payout": mechanic_payout,
    }
