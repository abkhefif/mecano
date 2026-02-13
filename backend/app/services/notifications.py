import uuid

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session

logger = structlog.get_logger()

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"


async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email. Currently logs only -- plug in Resend/SMTP later."""
    logger.info("email_send", to=to_email, subject=subject, body_preview=body[:100])
    # TODO: Integrate Resend or SMTP service
    return True


async def send_push(user_id: str, title: str, body: str, data: dict | None = None) -> bool:
    """Send a push notification via Expo Push API."""
    from app.models.user import User

    try:
        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
            user = result.scalar_one_or_none()
            if not user or not user.expo_push_token:
                logger.info("push_skip_no_token", user_id=user_id)
                return False

            payload = {
                "to": user.expo_push_token,
                "title": title,
                "body": body,
                "sound": "default",
            }
            if data:
                payload["data"] = data

            async with httpx.AsyncClient() as client:
                response = await client.post(EXPO_PUSH_URL, json=payload)
                response.raise_for_status()

            logger.info("push_sent", user_id=user_id, title=title)
            return True
    except Exception as e:
        logger.error("push_error", user_id=user_id, error=str(e))
        return False


async def send_booking_reminder(
    booking_id: str,
    buyer_email: str,
    buyer_name: str,
    mechanic_email: str,
    mechanic_name: str,
    vehicle_info: str,
    meeting_address: str,
    slot_date: str,
    slot_time: str,
    hours_before: int,
    buyer_phone: str | None = None,
    mechanic_phone: str | None = None,
) -> None:
    """Send reminder to both parties."""
    time_label = "demain" if hours_before == 24 else "dans 2h"

    # Email to buyer
    await send_email(
        to_email=buyer_email,
        subject=f"Rappel: Votre controle mecanique {time_label}",
        body=f"Bonjour {buyer_name},\n\nRappel de votre rendez-vous {time_label}.\n"
             f"Date: {slot_date} a {slot_time}\n"
             f"Vehicule: {vehicle_info}\n"
             f"Adresse: {meeting_address}\n"
             + (f"\nContact mecanicien: {mechanic_phone}" if hours_before <= 2 and mechanic_phone else "")
             + "\n\nL'equipe eMecano",
    )

    # Email to mechanic
    await send_email(
        to_email=mechanic_email,
        subject=f"Rappel: Controle mecanique {time_label}",
        body=f"Bonjour {mechanic_name},\n\nRappel de votre rendez-vous {time_label}.\n"
             f"Date: {slot_date} a {slot_time}\n"
             f"Vehicule: {vehicle_info}\n"
             f"Adresse: {meeting_address}\n"
             + (f"\nContact acheteur: {buyer_phone}" if hours_before <= 2 and buyer_phone else "")
             + "\n\nL'equipe eMecano",
    )

    logger.info("booking_reminder_sent", booking_id=booking_id, hours_before=hours_before)


async def create_notification(
    db: AsyncSession,
    user_id: uuid.UUID,
    notification_type: str,
    title: str,
    body: str,
    data: dict | None = None,
) -> "Notification":
    """Persist a notification and send a push notification."""
    from app.models.notification import Notification

    notification = Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body,
        data=data,
    )
    db.add(notification)
    await send_push(str(user_id), title, body, data=data)
    return notification
