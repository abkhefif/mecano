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


async def generate_pdf(
    booking: Booking,
    proof: ValidationProof,
    checklist: InspectionChecklist,
    mechanic_name: str,
) -> str:
    """Generate an inspection report PDF and upload it to storage.

    Returns the URL of the uploaded PDF.
    """
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=True)
    env.globals["status_label"] = _status_label
    env.globals["status_class"] = _status_class

    template = env.get_template("inspection_report.html")

    rec_label, rec_class = RECOMMENDATION_MAP.get(
        checklist.recommendation.value, ("Inconnu", "")
    )

    report_id = str(booking.id)[:8].upper()

    html_content = template.render(
        vehicle_brand=booking.vehicle_brand,
        vehicle_model=booking.vehicle_model,
        vehicle_year=booking.vehicle_year,
        entered_plate=proof.entered_plate,
        entered_odometer_km=f"{proof.entered_odometer_km:,}".replace(",", " "),
        meeting_address=booking.meeting_address,
        photo_plate_url=proof.photo_plate_url,
        photo_odometer_url=proof.photo_odometer_url,
        checklist=checklist,
        rec_label=rec_label,
        rec_class=rec_class,
        mechanic_name=mechanic_name,
        inspection_date=datetime.now(timezone.utc).strftime("%d/%m/%Y"),
        report_id=report_id,
    )

    pdf_bytes = await asyncio.to_thread(HTML(string=html_content).write_pdf)

    key = f"reports/{uuid.uuid4()}.pdf"
    url = await upload_file_bytes(pdf_bytes, key, "application/pdf")

    logger.info("pdf_generated", booking_id=str(booking.id), url=url)
    return url
