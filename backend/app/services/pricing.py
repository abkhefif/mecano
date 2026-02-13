from decimal import ROUND_HALF_UP, Decimal

from app.config import settings


def calculate_travel_fees(distance_km: float, free_zone_km: int) -> Decimal:
    """Calculate travel fees based on distance beyond the free zone."""
    billable_km = max(0, distance_km - free_zone_km)
    return (Decimal(str(billable_km)) * settings.TRAVEL_FEE_PER_KM).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def calculate_booking_pricing(
    distance_km: float, free_zone_km: int, obd_requested: bool = False
) -> dict[str, Decimal]:
    """Calculate full booking pricing breakdown."""
    base_price = settings.BASE_INSPECTION_PRICE
    if obd_requested:
        base_price = base_price + settings.OBD_SUPPLEMENT
    travel_fees = calculate_travel_fees(distance_km, free_zone_km)
    total_price = base_price + travel_fees
    commission_rate = settings.PLATFORM_COMMISSION_RATE
    commission_amount = (total_price * commission_rate).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    mechanic_payout = total_price - commission_amount

    return {
        "base_price": base_price,
        "travel_fees": travel_fees,
        "total_price": total_price,
        "commission_rate": commission_rate,
        "commission_amount": commission_amount,
        "mechanic_payout": mechanic_payout,
    }
