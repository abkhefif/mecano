import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from starlette.requests import Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.messages.constants import ALL_TEMPLATE_MESSAGES, ALL_TEMPLATES, BUYER_TEMPLATES, MECHANIC_TEMPLATES
from app.models.booking import Booking
from app.models.enums import BookingStatus, NotificationType, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.message import Message
from app.models.user import User
from app.schemas.message import MessageCreate, MessageResponse, TemplateMessage
from app.services.notifications import create_notification
from app.utils.contact_mask import mask_contacts
from app.utils.display_name import get_display_name
from app.utils.rate_limit import limiter

logger = structlog.get_logger()
router = APIRouter()

MAX_TEMPLATE_MESSAGES_PER_BOOKING = 20
MAX_CUSTOM_MESSAGES_PER_BOOKING = 30

MESSAGING_STATUSES = {
    BookingStatus.CONFIRMED,
    BookingStatus.AWAITING_MECHANIC_CODE,
    BookingStatus.CHECK_IN_DONE,
}


@router.get("/messages/templates", response_model=list[TemplateMessage])
@limiter.limit("60/minute")
async def get_templates(request: Request, role: str | None = None):
    """Return the list of pre-written message templates, optionally filtered by role."""
    if role == UserRole.BUYER.value:
        return BUYER_TEMPLATES
    if role == UserRole.MECHANIC.value:
        return MECHANIC_TEMPLATES
    return ALL_TEMPLATES


@router.get(
    "/bookings/{booking_id}/messages",
    response_model=list[MessageResponse],
)
@limiter.limit("60/minute")
async def get_booking_messages(
    request: Request,
    booking_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=100, description="Max messages to return"),
    offset: int = Query(0, ge=0, le=10000, description="Number of messages to skip"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List messages for a booking. Only the buyer or mechanic of the booking can see them.

    R-001/R-008: Supports pagination via limit and offset query parameters.
    """
    booking = await _get_booking_for_messaging(db, booking_id, user)

    result = await db.execute(
        select(Message)
        .where(Message.booking_id == booking.id)
        .options(selectinload(Message.sender))
        .order_by(Message.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    messages = result.scalars().all()

    return [_to_response(msg) for msg in messages]


@router.post(
    "/bookings/{booking_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("30/minute")
async def send_message(
    request: Request,
    booking_id: uuid.UUID,
    body: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Send a message in a booking conversation."""
    booking = await _get_booking_for_messaging(db, booking_id, user)

    # H-003: Admins can read but not send messages
    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admins cannot send messages. Use the admin panel for moderation.",
        )

    # Validate booking status allows messaging
    if booking.status not in MESSAGING_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Messaging is not available for bookings in '{booking.status.value}' status",
        )

    if body.is_template:
        # Validate the content matches a known template
        if body.content not in ALL_TEMPLATE_MESSAGES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid template message",
            )
        # M-06: Limit template messages to MAX_TEMPLATE_MESSAGES_PER_BOOKING per user per booking
        template_count_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.booking_id == booking.id,
                Message.sender_id == user.id,
                Message.is_template == True,  # noqa: E712
            )
        )
        template_count = template_count_result.scalar() or 0
        if template_count >= MAX_TEMPLATE_MESSAGES_PER_BOOKING:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Template message limit reached ({MAX_TEMPLATE_MESSAGES_PER_BOOKING} per booking)",
            )
    else:
        # Anti-spam: limit custom messages to MAX_CUSTOM_MESSAGES_PER_BOOKING per user per booking
        custom_count_result = await db.execute(
            select(func.count(Message.id)).where(
                Message.booking_id == booking.id,
                Message.sender_id == user.id,
                Message.is_template == False,  # noqa: E712
            )
        )
        custom_count = custom_count_result.scalar() or 0
        if custom_count >= MAX_CUSTOM_MESSAGES_PER_BOOKING:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Limite de messages atteinte ({MAX_CUSTOM_MESSAGES_PER_BOOKING} par réservation)",
            )
        # Mask contact information (phone, email, social media)
        body.content = mask_contacts(body.content)

    message = Message(
        booking_id=booking.id,
        sender_id=user.id,
        is_template=body.is_template,
        content=body.content,
    )
    db.add(message)
    await db.flush()

    logger.info(
        "message_sent",
        booking_id=str(booking.id),
        sender_id=str(user.id),
        is_template=body.is_template,
    )

    # Notify the other party about the new message
    if user.id == booking.buyer_id:
        # Sender is buyer, notify mechanic
        recipient_id = booking.mechanic.user_id if booking.mechanic else None
    else:
        # Sender is mechanic, notify buyer
        recipient_id = booking.buyer_id
    if recipient_id is not None:
        await create_notification(
            db=db,
            user_id=recipient_id,
            notification_type=NotificationType.NEW_MESSAGE,
            title="Nouveau message",
            body=f"{get_display_name(user)} vous a envoye un message.",
            data={"booking_id": str(booking.id), "message_id": str(message.id)},
        )

    # Build response with sender name
    return MessageResponse(
        id=message.id,
        booking_id=message.booking_id,
        sender_id=message.sender_id,
        is_template=message.is_template,
        content=message.content,
        created_at=message.created_at,
        sender_name=get_display_name(user),
    )


async def _get_booking_for_messaging(
    db: AsyncSession, booking_id: uuid.UUID, user: User
) -> Booking:
    """Fetch a booking and verify the user is a participant (buyer or mechanic)."""
    result = await db.execute(
        select(Booking)
        .where(Booking.id == booking_id)
        .options(selectinload(Booking.mechanic))
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found"
        )

    # BUG-015: Allow admins to read messages for dispute resolution (read-only)
    if user.role == UserRole.ADMIN:
        return booking

    # Check user is buyer or mechanic for this booking
    is_buyer = booking.buyer_id == user.id
    is_mechanic = False
    if user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile and booking.mechanic_id == profile.id:
            is_mechanic = True

    if not is_buyer and not is_mechanic:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a participant of this booking",
        )

    return booking


def _to_response(msg: Message) -> MessageResponse:
    """Convert a Message ORM object to a response with sender name."""
    sender_name = None
    if msg.sender:
        sender_name = get_display_name(msg.sender)
    return MessageResponse(
        id=msg.id,
        booking_id=msg.booking_id,
        sender_id=msg.sender_id,
        is_template=msg.is_template,
        content=msg.content,
        created_at=msg.created_at,
        sender_name=sender_name,
    )
