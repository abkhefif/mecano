from decimal import Decimal

import pytest

from app.services.pricing import calculate_booking_pricing, calculate_travel_fees
from app.utils.code_generator import generate_check_in_code
from app.utils.geo import calculate_distance_km, get_city_coords


class TestDistanceCalculation:
    def test_same_point(self):
        dist = calculate_distance_km(43.6047, 1.4442, 43.6047, 1.4442)
        assert dist == 0.0

    def test_toulouse_to_montpellier(self):
        dist = calculate_distance_km(43.6047, 1.4442, 43.6108, 3.8767)
        assert 190 < dist < 210  # ~196 km

    def test_short_distance(self):
        dist = calculate_distance_km(43.6047, 1.4442, 43.6100, 1.4500)
        assert dist < 1.0  # Less than 1 km


class TestCityCoords:
    def test_known_city(self):
        coords = get_city_coords("toulouse")
        assert coords is not None
        assert abs(coords[0] - 43.6047) < 0.01

    def test_known_city_case_insensitive(self):
        coords = get_city_coords("TOULOUSE")
        assert coords is not None

    def test_unknown_city(self):
        assert get_city_coords("nonexistent_city") is None


class TestTravelFees:
    def test_within_free_zone(self):
        fees = calculate_travel_fees(8.0, 10)
        assert fees == Decimal("0.00")

    def test_exactly_at_free_zone(self):
        fees = calculate_travel_fees(10.0, 10)
        assert fees == Decimal("0.00")

    def test_beyond_free_zone(self):
        fees = calculate_travel_fees(20.0, 10)
        assert fees == Decimal("3.00")

    def test_long_distance(self):
        fees = calculate_travel_fees(50.0, 10)
        assert fees == Decimal("12.00")

    def test_zero_free_zone(self):
        fees = calculate_travel_fees(10.0, 0)
        assert fees == Decimal("3.00")


class TestBookingPricing:
    def test_no_travel_fees(self):
        pricing = calculate_booking_pricing(5.0, 10)
        assert pricing["base_price"] == Decimal("50.00")
        assert pricing["travel_fees"] == Decimal("0.00")
        assert pricing["total_price"] == Decimal("50.00")
        assert pricing["commission_amount"] == Decimal("10.00")
        assert pricing["mechanic_payout"] == Decimal("40.00")

    def test_with_travel_fees(self):
        pricing = calculate_booking_pricing(30.0, 10)
        assert pricing["base_price"] == Decimal("50.00")
        assert pricing["travel_fees"] == Decimal("6.00")
        assert pricing["total_price"] == Decimal("56.00")
        assert pricing["commission_rate"] == Decimal("0.20")
        assert pricing["commission_amount"] == Decimal("11.20")
        assert pricing["mechanic_payout"] == Decimal("44.80")


class TestCodeGenerator:
    def test_code_is_4_digits(self):
        code = generate_check_in_code()
        assert len(code) == 4
        assert code.isdigit()

    def test_code_randomness(self):
        codes = {generate_check_in_code() for _ in range(100)}
        assert len(codes) > 10  # Should have variety
