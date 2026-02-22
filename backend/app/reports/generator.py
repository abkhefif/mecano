import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import structlog
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML

from app.models.booking import Booking
from app.models.inspection import InspectionChecklist
from app.models.validation_proof import ValidationProof
from app.services.storage import upload_file_bytes

logger = structlog.get_logger()

TEMPLATE_DIR = Path(__file__).parent / "templates"

# AUD-B06: Warn at import time if the templates directory is missing
if not TEMPLATE_DIR.exists():
    import warnings
    warnings.warn(f"Templates directory not found: {TEMPLATE_DIR}")

# AUD-M03: Create Jinja2 environment once at module level instead of per-call.
# SEC-020: autoescape=True prevents template injection (XSS) in generated HTML
_jinja_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)

STATUS_LABELS = {
    # Component
    "ok": "OK",
    "warning": "Attention",
    "critical": "Critique",
    # Fluids
    "low": "Bas",
    "empty": "Vide",
    # Battery
    "weak": "Faible",
    "dead": "HS",
    # Suspension
    "worn": "Use",
    "broken": "Casse",
    # Body
    "good": "Bon",
    "average": "Moyen",
    "bad": "Mauvais",
    # Exhaust
    "rust": "Rouille",
    "hole": "Troue",
    # Lights
    "defect": "Defaillant",
    # Drive
    "normal": "Normal",
    "suspect": "Suspect",
    "dangerous": "Dangereux",
}

STATUS_CLASSES = {
    "ok": "status-ok",
    "good": "status-ok",
    "normal": "status-ok",
    "warning": "status-warning",
    "low": "status-warning",
    "weak": "status-warning",
    "worn": "status-warning",
    "average": "status-warning",
    "rust": "status-warning",
    "suspect": "status-warning",
    "critical": "status-critical",
    "empty": "status-critical",
    "dead": "status-critical",
    "broken": "status-critical",
    "bad": "status-critical",
    "hole": "status-critical",
    "defect": "status-critical",
    "dangerous": "status-critical",
}

RECOMMENDATION_MAP = {
    "buy": ("Achat recommande", "rec-buy"),
    "negotiate": ("A negocier", "rec-negotiate"),
    "avoid": ("Achat deconseille", "rec-avoid"),
}


def _status_label(value) -> str:
    v = value.value if hasattr(value, "value") else str(value)
    return STATUS_LABELS.get(v, v)


def _status_class(value) -> str:
    v = value.value if hasattr(value, "value") else str(value)
    return STATUS_CLASSES.get(v, "")


# AUD-004: Register Jinja2 template globals once at module level instead of
# mutating them on every generate_pdf call.
_jinja_env.globals["status_label"] = _status_label
_jinja_env.globals["status_class"] = _status_class


async def generate_pdf(
    booking: Booking,
    proof: ValidationProof,
    checklist: InspectionChecklist,
    mechanic_name: str,
    additional_photo_urls: list[str] | None = None,
) -> str:
    """Generate an inspection report PDF and upload it to storage.

    Returns the URL of the uploaded PDF.
    """
    template = _jinja_env.get_template("inspection_report.html")

    rec_label, rec_class = RECOMMENDATION_MAP.get(
        checklist.recommendation.value, ("Inconnu", "")
    )

    report_id = str(booking.id)[:8].upper()

    html_content = template.render(
        vehicle_brand=booking.vehicle_brand,
        vehicle_model=booking.vehicle_model,
        vehicle_year=booking.vehicle_year,
        entered_plate=proof.entered_plate or "Non renseignée",
        entered_odometer_km=f"{proof.entered_odometer_km:,}".replace(",", " "),
        meeting_address=booking.meeting_address,
        photo_plate_url=proof.photo_plate_url,
        photo_odometer_url=proof.photo_odometer_url,
        additional_photo_urls=additional_photo_urls or [],
        checklist=checklist,
        rec_label=rec_label,
        rec_class=rec_class,
        mechanic_name=mechanic_name,
        inspection_date=datetime.now(timezone.utc).strftime("%d/%m/%Y"),
        report_id=report_id,
    )

    # AUD-B10: Timeout on PDF generation to prevent indefinite hangs
    # Move HTML constructor into thread to avoid blocking event loop
    pdf_bytes = await asyncio.wait_for(
        asyncio.to_thread(lambda: HTML(string=html_content).write_pdf()),
        timeout=30,
    )

    key = f"reports/{uuid.uuid4()}.pdf"
    url = await upload_file_bytes(pdf_bytes, key, "application/pdf")

    logger.info("pdf_generated", booking_id=str(booking.id), url=url)
    return url


async def generate_payment_receipt(booking_data: dict) -> bytes:
    """Generate a payment receipt PDF from booking data.

    Returns the raw PDF bytes (not uploaded to storage).
    """
    template = _jinja_env.get_template("payment_receipt.html")

    html_content = template.render(**booking_data)

    # AUD-B10: Timeout on PDF generation to prevent indefinite hangs
    pdf_bytes = await asyncio.wait_for(
        asyncio.to_thread(lambda: HTML(string=html_content).write_pdf()),
        timeout=30,
    )

    logger.info("payment_receipt_generated", receipt_number=booking_data.get("receipt_number"))
    return pdf_bytes
