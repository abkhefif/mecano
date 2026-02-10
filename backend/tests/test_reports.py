import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest

from app.models.booking import Booking
from app.models.enums import (
    BatteryStatus,
    BodyStatus,
    BookingStatus,
    ComponentStatus,
    ExhaustStatus,
    FluidStatus,
    LightStatus,
    Recommendation,
    SuspensionStatus,
    UploadedBy,
    VehicleType,
)
from app.models.inspection import InspectionChecklist
from app.models.validation_proof import ValidationProof


@pytest.mark.asyncio
async def test_generate_pdf():
    """Test PDF generation with mocked storage upload."""
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
        mechanic_id=uuid.uuid4(),
        status=BookingStatus.CHECK_IN_DONE,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Peugeot",
        vehicle_model="308",
        vehicle_year=2019,
        meeting_address="123 Rue Test, Toulouse",
        meeting_lat=43.61,
        meeting_lng=1.45,
        distance_km=5.0,
        base_price=Decimal("50.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("50.00"),
        commission_rate=Decimal("0.20"),
        commission_amount=Decimal("10.00"),
        mechanic_payout=Decimal("40.00"),
    )

    proof = ValidationProof(
        id=uuid.uuid4(),
        booking_id=booking.id,
        photo_plate_url="https://storage.emecano.dev/proofs/plate.jpg",
        photo_odometer_url="https://storage.emecano.dev/proofs/odo.jpg",
        entered_plate="AB-123-CD",
        entered_odometer_km=85000,
        uploaded_by=UploadedBy.MECHANIC,
    )

    checklist = InspectionChecklist(
        id=uuid.uuid4(),
        booking_id=booking.id,
        brakes=ComponentStatus.OK,
        tires=ComponentStatus.WARNING,
        fluids=FluidStatus.OK,
        battery=BatteryStatus.OK,
        suspension=SuspensionStatus.OK,
        body=BodyStatus.GOOD,
        exhaust=ExhaustStatus.OK,
        lights=LightStatus.OK,
        test_drive_done=True,
        test_drive_behavior=None,
        remarks="Light wear on front tires, consider replacing within 10000 km",
        recommendation=Recommendation.BUY,
    )

    with patch("app.reports.generator.upload_file_bytes", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = "https://storage.emecano.dev/reports/test.pdf"

        from app.reports.generator import generate_pdf

        url = await generate_pdf(booking, proof, checklist, "Jean Dupont")

        assert url == "https://storage.emecano.dev/reports/test.pdf"
        mock_upload.assert_called_once()
        call_args = mock_upload.call_args
        assert call_args[0][2] == "application/pdf"
        # Verify PDF bytes were generated (non-empty)
        assert len(call_args[0][0]) > 0


@pytest.mark.asyncio
async def test_generate_pdf_avoid_recommendation():
    """Test PDF generation with 'avoid' recommendation."""
    booking = Booking(
        id=uuid.uuid4(),
        buyer_id=uuid.uuid4(),
        mechanic_id=uuid.uuid4(),
        status=BookingStatus.CHECK_IN_DONE,
        vehicle_type=VehicleType.CAR,
        vehicle_brand="Renault",
        vehicle_model="Clio",
        vehicle_year=2015,
        meeting_address="Montpellier",
        meeting_lat=43.61,
        meeting_lng=3.87,
        distance_km=10.0,
        base_price=Decimal("50.00"),
        travel_fees=Decimal("0.00"),
        total_price=Decimal("50.00"),
        commission_rate=Decimal("0.20"),
        commission_amount=Decimal("10.00"),
        mechanic_payout=Decimal("40.00"),
    )

    proof = ValidationProof(
        id=uuid.uuid4(),
        booking_id=booking.id,
        photo_plate_url="https://storage.emecano.dev/proofs/plate2.jpg",
        photo_odometer_url="https://storage.emecano.dev/proofs/odo2.jpg",
        entered_plate="EF-456-GH",
        entered_odometer_km=200000,
        uploaded_by=UploadedBy.MECHANIC,
    )

    checklist = InspectionChecklist(
        id=uuid.uuid4(),
        booking_id=booking.id,
        brakes=ComponentStatus.CRITICAL,
        tires=ComponentStatus.CRITICAL,
        fluids=FluidStatus.LOW,
        battery=BatteryStatus.WEAK,
        suspension=SuspensionStatus.WORN,
        body=BodyStatus.BAD,
        exhaust=ExhaustStatus.HOLE,
        lights=LightStatus.DEFECT,
        test_drive_done=True,
        test_drive_behavior=None,
        remarks="Major issues everywhere. Do not buy.",
        recommendation=Recommendation.AVOID,
    )

    with patch("app.reports.generator.upload_file_bytes", new_callable=AsyncMock) as mock_upload:
        mock_upload.return_value = "https://storage.emecano.dev/reports/test2.pdf"

        from app.reports.generator import generate_pdf

        url = await generate_pdf(booking, proof, checklist, "Pierre Martin")
        assert url == "https://storage.emecano.dev/reports/test2.pdf"
