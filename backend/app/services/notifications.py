import asyncio
import uuid
from html import escape
from typing import Set

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import async_session
from app.utils.log_mask import mask_email

logger = structlog.get_logger()

# Keep references to background tasks to prevent GC collection
_background_tasks: Set[asyncio.Task] = set()

EXPO_PUSH_URL = "https://exp.host/--/api/v2/push/send"

_push_client: httpx.AsyncClient | None = None


def _get_push_client() -> httpx.AsyncClient:
    global _push_client
    if _push_client is None or _push_client.is_closed:
        _push_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
        )
    return _push_client


async def send_email(to_email: str, subject: str, body: str) -> bool:
    """Send an email via Resend API.

    If RESEND_API_KEY is not configured, gracefully logs and returns True (dev mode).
    """
    if not settings.RESEND_API_KEY:
        logger.info("email_send_dev_mode", to=mask_email(to_email), subject=subject)
        return True

    try:
        client = _get_push_client()
        response = await client.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
            json={
                "from": "eMecano <noreply@emecano.fr>",
                "to": [to_email],
                "subject": subject,
                "html": body,
            },
        )
        if response.is_success:
            logger.info("email_sent", to=mask_email(to_email), subject=subject)
            return True
        else:
            logger.error(
                "email_send_failed",
                to=mask_email(to_email),
                subject=subject,
                status_code=response.status_code,
            )
            return False
    except Exception as exc:
        logger.error("email_send_error", to=mask_email(to_email), subject=subject, error=str(exc))
        return False


async def send_push(user_id: str, title: str, body: str, data: dict | None = None, db: AsyncSession | None = None) -> bool:
    """Send a push notification via Expo Push API.

    If a ``db`` session is provided it will be reused to look up the user's
    push token; otherwise a new session is opened (backward-compatible).
    """
    from app.models.user import User

    async def _do_send(session: AsyncSession) -> bool:
        result = await session.execute(select(User).where(User.id == uuid.UUID(user_id)))
        user = result.scalar_one_or_none()
        if not user or not user.expo_push_token:
            logger.info("push_skip_no_token", user_id=user_id)
            return False

        # R-010: Truncate title/body before sending to Expo to avoid
        # oversized push notification payloads being silently dropped.
        truncated_title = title[:50] if title else title
        truncated_body = body[:200] if body else body

        payload = {
            "to": user.expo_push_token,
            "title": truncated_title,
            "body": truncated_body,
            "sound": "default",
        }
        if data:
            payload["data"] = data
            # Add iOS notification category for actionable notifications
            notification_type = data.get("type")
            if notification_type == "booking_created":
                payload["categoryId"] = "booking_request"

        client = _get_push_client()
        response = await client.post(EXPO_PUSH_URL, json=payload)
        response.raise_for_status()

        # Parse response to check for push token errors
        try:
            resp_data = response.json()
            if isinstance(resp_data, dict) and "data" in resp_data:
                ticket = resp_data["data"]
                # Expo returns a single ticket object when sending to one token
                if isinstance(ticket, dict):
                    ticket_status = ticket.get("status")
                    if ticket_status == "error":
                        error_detail = ticket.get("details", {})
                        error_code = error_detail.get("error") if isinstance(error_detail, dict) else None
                        if error_code == "DeviceNotRegistered":
                            logger.warning(
                                "push_token_invalid",
                                user_id=user_id,
                                token=user.expo_push_token,
                                error="DeviceNotRegistered",
                            )
                            # Cleanup: clear the invalid push token
                            user.expo_push_token = None
                            await session.flush()
                        else:
                            logger.warning(
                                "push_ticket_error",
                                user_id=user_id,
                                message=ticket.get("message"),
                            )
        except Exception:
            # Don't fail the overall operation if receipt parsing fails
            logger.debug("push_receipt_parse_skipped", user_id=user_id)

        logger.info("push_sent", user_id=user_id, title=title)
        return True

    try:
        if db is not None:
            return await _do_send(db)
        else:
            async with async_session() as new_db:
                return await _do_send(new_db)
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

    # M-02: Escape user-supplied values before inserting into HTML email bodies
    safe_buyer_name = escape(buyer_name)
    safe_mechanic_name = escape(mechanic_name)
    safe_vehicle_info = escape(vehicle_info)
    safe_meeting_address = escape(meeting_address)

    # Email to buyer
    await send_email(
        to_email=buyer_email,
        subject=f"Rappel: Votre controle mecanique {time_label}",
        body=f"Bonjour {safe_buyer_name},\n\nRappel de votre rendez-vous {time_label}.\n"
             f"Date: {slot_date} a {slot_time}\n"
             f"Vehicule: {safe_vehicle_info}\n"
             f"Adresse: {safe_meeting_address}\n"
             "\n\nL'equipe eMecano",
    )

    # Email to mechanic
    await send_email(
        to_email=mechanic_email,
        subject=f"Rappel: Controle mecanique {time_label}",
        body=f"Bonjour {safe_mechanic_name},\n\nRappel de votre rendez-vous {time_label}.\n"
             f"Date: {slot_date} a {slot_time}\n"
             f"Vehicule: {safe_vehicle_info}\n"
             f"Adresse: {safe_meeting_address}\n"
             "\n\nL'equipe eMecano",
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

    # Ensure the notification type is included in the data dict
    # so the mobile app can route to the correct screen via deep linking
    push_data = dict(data) if data else {}
    if "type" not in push_data:
        # notification_type can be a string or an enum with a .value attribute
        type_value = notification_type.value if hasattr(notification_type, "value") else notification_type
        push_data["type"] = type_value

    notification = Notification(
        user_id=user_id,
        type=notification_type,
        title=title,
        body=body,
        data=push_data,
    )
    db.add(notification)
    await db.flush()
    # PERF-002: Fire push notification in background to avoid blocking the response
    # by 100-500ms (Expo API round-trip). The flush above persists the notification.
    # send_push will open its own DB session (db=None) for token lookup and
    # DeviceNotRegistered cleanup, so it is safe after the caller's session commits.
    task = asyncio.create_task(send_push(str(user_id), title, body, data=push_data))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return notification
