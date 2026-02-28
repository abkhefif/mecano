import uuid
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_mechanic, get_current_user, get_verified_buyer
from app.models.availability import Availability
from app.models.booking import Booking
from app.models.date_proposal import DateProposal
from app.models.enums import BookingStatus, NotificationType, ProposalStatus, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.schemas.proposal import (
    ProposalCounterRequest,
    ProposalCreateRequest,
    ProposalHistoryResponse,
    ProposalResponse,
)
from app.services.notifications import create_notification
from app.services.pricing import calculate_booking_pricing
from app.services.stripe_service import cancel_payment_intent, create_payment_intent, StripeServiceError
from app.config import settings
from app.utils.geo import calculate_distance_km
from app.utils.rate_limit import limiter

logger = structlog.get_logger()
router = APIRouter()

PROPOSAL_EXPIRY_HOURS = 48
MAX_ROUNDS = 3
SLOT_DURATION_MINUTES = settings.BOOKING_SLOT_DURATION_MINUTES


def _proposal_to_response(proposal: DateProposal, buyer: User | None = None, mechanic_user: User | None = None) -> ProposalResponse:
    resp = ProposalResponse.model_validate(proposal)
    if buyer:
        resp.buyer_name = buyer.first_name or buyer.email.split("@")[0]
    if mechanic_user:
        resp.mechanic_name = mechanic_user.first_name or mechanic_user.email.split("@")[0]
    return resp


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def create_proposal(
    request: Request,
    body: ProposalCreateRequest,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
):
    """Create a date proposal from buyer to mechanic."""
    # Fetch mechanic profile
    mech_result = await db.execute(
        select(MechanicProfile)
        .where(MechanicProfile.id == body.mechanic_id)
        .options(selectinload(MechanicProfile.user))
    )
    mechanic = mech_result.scalar_one_or_none()
    if not mechanic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic not found")

    if mechanic.user_id == buyer.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot propose to yourself")

    if not mechanic.is_active:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic is not currently active")

    if mechanic.suspended_until and mechanic.suspended_until > datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic is currently unavailable")

    if body.vehicle_type.value not in mechanic.accepted_vehicle_types:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic does not accept this vehicle type")

    if body.obd_requested and not mechanic.has_obd_diagnostic:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This mechanic does not offer OBD diagnostic")

    # Validate proposed date is in the future
    proposed_dt = datetime.combine(body.proposed_date, time.fromisoformat(body.proposed_time), tzinfo=timezone.utc)
    if proposed_dt <= datetime.now(timezone.utc) + timedelta(hours=settings.BOOKING_MINIMUM_ADVANCE_HOURS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposed date must be at least {settings.BOOKING_MINIMUM_ADVANCE_HOURS} hours in the future",
        )

    # Check no pending proposal already exists for this buyer+mechanic pair
    existing = await db.execute(
        select(DateProposal).where(
            DateProposal.buyer_id == buyer.id,
            DateProposal.mechanic_id == body.mechanic_id,
            DateProposal.status == ProposalStatus.PENDING,
        )
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have a pending proposal with this mechanic",
        )

    now = datetime.now(timezone.utc)
    proposal = DateProposal(
        buyer_id=buyer.id,
        mechanic_id=body.mechanic_id,
        proposed_date=body.proposed_date,
        proposed_time=body.proposed_time,
        message=body.message,
        status=ProposalStatus.PENDING,
        round_number=1,
        responded_by="buyer",
        vehicle_type=body.vehicle_type,
        vehicle_brand=body.vehicle_brand,
        vehicle_model=body.vehicle_model,
        vehicle_year=body.vehicle_year,
        vehicle_plate=body.vehicle_plate,
        meeting_address=body.meeting_address,
        meeting_lat=body.meeting_lat,
        meeting_lng=body.meeting_lng,
        obd_requested=body.obd_requested,
        created_at=now,
        expires_at=now + timedelta(hours=PROPOSAL_EXPIRY_HOURS),
    )
    db.add(proposal)
    await db.flush()

    # Notify mechanic
    await create_notification(
        db=db,
        user_id=mechanic.user_id,
        notification_type=NotificationType.PROPOSAL_RECEIVED,
        title="Nouvelle proposition de RDV",
        body=f"Un acheteur vous propose un RDV le {body.proposed_date.strftime('%d/%m')} a {body.proposed_time}.",
        data={"proposal_id": str(proposal.id), "type": "proposal_received"},
    )

    await db.flush()
    logger.info("proposal_created", proposal_id=str(proposal.id), buyer_id=str(buyer.id), mechanic_id=str(body.mechanic_id))

    return _proposal_to_response(proposal, buyer=buyer, mechanic_user=mechanic.user)


@router.get("")
@limiter.limit("30/minute")
async def list_proposals(
    request: Request,
    status_filter: ProposalStatus | None = Query(None, alias="status"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List proposals for the current user (buyer or mechanic)."""
    query = select(DateProposal).options(
        selectinload(DateProposal.buyer),
        selectinload(DateProposal.mechanic).selectinload(MechanicProfile.user),
    )

    if user.role == UserRole.BUYER:
        query = query.where(DateProposal.buyer_id == user.id)
    elif user.role == UserRole.MECHANIC:
        mech_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = mech_result.scalar_one_or_none()
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic profile not found")
        query = query.where(DateProposal.mechanic_id == profile.id)
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")

    if status_filter:
        query = query.where(DateProposal.status == status_filter)

    # Only show the latest proposal in each chain (no parent_id or is the leaf)
    query = query.order_by(DateProposal.created_at.desc()).limit(50)

    result = await db.execute(query)
    proposals = result.scalars().all()

    return [
        _proposal_to_response(
            p,
            buyer=p.buyer,
            mechanic_user=p.mechanic.user if p.mechanic else None,
        )
        for p in proposals
    ]


@router.get("/{proposal_id}")
@limiter.limit("30/minute")
async def get_proposal(
    request: Request,
    proposal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a proposal with its full negotiation history."""
    proposal = await _get_proposal_for_user(db, proposal_id, user)

    # Build history chain by following parent_id
    history = []
    current = proposal
    while current.parent_id:
        parent_result = await db.execute(
            select(DateProposal)
            .where(DateProposal.id == current.parent_id)
            .options(
                selectinload(DateProposal.buyer),
                selectinload(DateProposal.mechanic).selectinload(MechanicProfile.user),
            )
        )
        parent = parent_result.scalar_one_or_none()
        if not parent:
            break
        history.append(_proposal_to_response(
            parent,
            buyer=parent.buyer,
            mechanic_user=parent.mechanic.user if parent.mechanic else None,
        ))
        current = parent

    # Load buyer/mechanic for current proposal
    await _load_proposal_relations(db, proposal)

    return ProposalHistoryResponse(
        current=_proposal_to_response(
            proposal,
            buyer=proposal.buyer,
            mechanic_user=proposal.mechanic.user if proposal.mechanic else None,
        ),
        history=list(reversed(history)),
    )


@router.patch("/{proposal_id}/accept")
@limiter.limit("10/minute")
async def accept_proposal(
    request: Request,
    proposal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accept a proposal. Creates an availability slot + booking automatically."""
    proposal = await _get_proposal_for_user(db, proposal_id, user)

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal is not pending")

    # Verify it's the other party's turn to respond
    _verify_responder(proposal, user)

    # AUDIT-11 + AUDIT-1: Enforce same checks as get_verified_buyer for buyer role
    if user.role == UserRole.BUYER:
        if not user.is_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Vérification d'email requise pour accepter une proposition.",
            )
        if not user.phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un numéro de téléphone est requis. Mettez à jour votre profil.",
            )
    elif user.role == UserRole.MECHANIC:
        if not user.phone:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Un numéro de téléphone est requis. Mettez à jour votre profil.",
            )

    # Fetch mechanic profile for pricing
    mech_result = await db.execute(
        select(MechanicProfile)
        .where(MechanicProfile.id == proposal.mechanic_id)
        .options(selectinload(MechanicProfile.user))
    )
    mechanic = mech_result.scalar_one_or_none()
    if not mechanic:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic not found")

    if not mechanic.stripe_account_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mechanic has not completed payment onboarding",
        )

    # AUDIT-1: Verify mechanic has phone
    if mechanic.user and not mechanic.user.phone:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Le mécanicien doit d'abord renseigner son numéro de téléphone.",
        )

    # Validate proposed date is still in the future
    proposed_dt = datetime.combine(
        proposal.proposed_date,
        time.fromisoformat(proposal.proposed_time),
        tzinfo=timezone.utc,
    )
    now = datetime.now(timezone.utc)
    if proposed_dt <= now + timedelta(hours=settings.BOOKING_MINIMUM_ADVANCE_HOURS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The proposed date has passed or is too soon",
        )

    # AUDIT-7: FIN-04 — Stripe authorizations expire after 7 days
    max_advance = timedelta(days=settings.STRIPE_AUTH_MAX_ADVANCE_DAYS)
    if proposed_dt - now > max_advance:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"La date proposée est trop lointaine ({settings.STRIPE_AUTH_MAX_ADVANCE_DAYS} jours max)",
        )

    # Create a 30-min availability slot for the mechanic
    slot_start = time.fromisoformat(proposal.proposed_time)
    slot_end_dt = datetime.combine(proposal.proposed_date, slot_start) + timedelta(minutes=SLOT_DURATION_MINUTES)
    slot_end = slot_end_dt.time()

    availability = Availability(
        id=uuid.uuid4(),
        mechanic_id=proposal.mechanic_id,
        date=proposal.proposed_date,
        start_time=slot_start,
        end_time=slot_end,
        is_booked=True,
    )
    db.add(availability)
    await db.flush()

    # Calculate pricing
    if mechanic.city_lat is None or mechanic.city_lng is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Mechanic has not set their service location")

    distance_km = calculate_distance_km(
        mechanic.city_lat, mechanic.city_lng,
        float(proposal.meeting_lat), float(proposal.meeting_lng),
    )
    pricing = calculate_booking_pricing(distance_km, mechanic.free_zone_km, obd_requested=proposal.obd_requested)

    # Create Stripe PaymentIntent
    amount_cents = int((pricing["total_price"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    commission_cents = int((pricing["commission_amount"] * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    # Determine buyer_id for Stripe metadata
    buyer_id = proposal.buyer_id

    try:
        intent = await create_payment_intent(
            amount_cents=amount_cents,
            mechanic_stripe_account_id=mechanic.stripe_account_id,
            commission_cents=commission_cents,
            metadata={"buyer_id": str(buyer_id), "mechanic_id": str(mechanic.id), "proposal_id": str(proposal.id)},
            idempotency_key=f"proposal_{proposal.id}_{uuid.uuid4().hex[:8]}",
        )
    except StripeServiceError as e:
        logger.error("proposal_accept_stripe_error", error=str(e), proposal_id=str(proposal.id))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Payment processing failed")

    # Create booking
    try:
        booking = Booking(
            buyer_id=buyer_id,
            mechanic_id=mechanic.id,
            availability_id=availability.id,
            status=BookingStatus.PENDING_ACCEPTANCE,
            vehicle_type=proposal.vehicle_type,
            vehicle_brand=proposal.vehicle_brand,
            vehicle_model=proposal.vehicle_model,
            vehicle_year=proposal.vehicle_year,
            vehicle_plate=proposal.vehicle_plate,
            meeting_address=proposal.meeting_address,
            meeting_lat=float(proposal.meeting_lat),
            meeting_lng=float(proposal.meeting_lng),
            distance_km=round(distance_km, 2),
            obd_requested=proposal.obd_requested,
            stripe_payment_intent_id=intent["id"],
            **pricing,
        )
        db.add(booking)
        await db.flush()

        # If mechanic accepted, auto-confirm the booking
        if user.role == UserRole.MECHANIC:
            booking.status = BookingStatus.CONFIRMED
            booking.confirmed_at = datetime.now(timezone.utc)
            await db.flush()

    except Exception as e:
        logger.exception("proposal_accept_booking_failed", error=str(e))
        try:
            await cancel_payment_intent(intent["id"])
        except Exception:
            pass
        raise

    # Update proposal status
    proposal.status = ProposalStatus.ACCEPTED
    proposal.booking_id = booking.id
    await db.flush()

    # Notify the other party
    if user.role == UserRole.MECHANIC:
        # Notify buyer
        await create_notification(
            db=db,
            user_id=buyer_id,
            notification_type=NotificationType.PROPOSAL_ACCEPTED,
            title="Proposition acceptee !",
            body=f"Le mecanicien a accepte votre proposition pour le {proposal.proposed_date.strftime('%d/%m')} a {proposal.proposed_time}.",
            data={"proposal_id": str(proposal.id), "booking_id": str(booking.id), "type": "proposal_accepted"},
        )
    else:
        # Notify mechanic
        await create_notification(
            db=db,
            user_id=mechanic.user_id,
            notification_type=NotificationType.PROPOSAL_ACCEPTED,
            title="Proposition acceptee !",
            body=f"L'acheteur a accepte le RDV le {proposal.proposed_date.strftime('%d/%m')} a {proposal.proposed_time}.",
            data={"proposal_id": str(proposal.id), "booking_id": str(booking.id), "type": "proposal_accepted"},
        )

    await db.flush()
    logger.info("proposal_accepted", proposal_id=str(proposal.id), booking_id=str(booking.id))

    return {
        "status": "accepted",
        "proposal_id": str(proposal.id),
        "booking_id": str(booking.id),
        "client_secret": intent.get("client_secret"),
    }


@router.patch("/{proposal_id}/refuse")
@limiter.limit("10/minute")
async def refuse_proposal(
    request: Request,
    proposal_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Refuse a proposal without counter-proposing."""
    proposal = await _get_proposal_for_user(db, proposal_id, user)

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal is not pending")

    _verify_responder(proposal, user)

    proposal.status = ProposalStatus.REFUSED
    await db.flush()

    # Load mechanic for notification
    mech_result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.id == proposal.mechanic_id).options(selectinload(MechanicProfile.user))
    )
    mechanic = mech_result.scalar_one_or_none()

    # Notify the other party
    if user.role == UserRole.MECHANIC:
        await create_notification(
            db=db,
            user_id=proposal.buyer_id,
            notification_type=NotificationType.PROPOSAL_REFUSED,
            title="Proposition refusee",
            body="Le mecanicien a decline votre proposition de rendez-vous.",
            data={"proposal_id": str(proposal.id), "type": "proposal_refused"},
        )
    else:
        if mechanic:
            await create_notification(
                db=db,
                user_id=mechanic.user_id,
                notification_type=NotificationType.PROPOSAL_REFUSED,
                title="Proposition refusee",
                body="L'acheteur a decline votre contre-proposition.",
                data={"proposal_id": str(proposal.id), "type": "proposal_refused"},
            )

    await db.flush()
    logger.info("proposal_refused", proposal_id=str(proposal.id))
    return {"status": "refused", "proposal_id": str(proposal.id)}


@router.patch("/{proposal_id}/counter")
@limiter.limit("10/minute")
async def counter_proposal(
    request: Request,
    proposal_id: uuid.UUID,
    body: ProposalCounterRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Counter-propose with a new date/time."""
    proposal = await _get_proposal_for_user(db, proposal_id, user)

    if proposal.status != ProposalStatus.PENDING:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Proposal is not pending")

    _verify_responder(proposal, user)

    if proposal.round_number >= MAX_ROUNDS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Maximum {MAX_ROUNDS} negotiation rounds reached",
        )

    # Validate proposed date is in the future
    proposed_dt = datetime.combine(body.proposed_date, time.fromisoformat(body.proposed_time), tzinfo=timezone.utc)
    if proposed_dt <= datetime.now(timezone.utc) + timedelta(hours=settings.BOOKING_MINIMUM_ADVANCE_HOURS):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Proposed date must be at least {settings.BOOKING_MINIMUM_ADVANCE_HOURS} hours in the future",
        )

    # Mark old proposal as counter-proposed
    proposal.status = ProposalStatus.COUNTER_PROPOSED
    await db.flush()

    # Create new proposal
    now = datetime.now(timezone.utc)
    new_proposal = DateProposal(
        buyer_id=proposal.buyer_id,
        mechanic_id=proposal.mechanic_id,
        proposed_date=body.proposed_date,
        proposed_time=body.proposed_time,
        message=body.message,
        status=ProposalStatus.PENDING,
        round_number=proposal.round_number + 1,
        parent_id=proposal.id,
        responded_by="mechanic" if user.role == UserRole.MECHANIC else "buyer",
        # Carry forward vehicle info
        vehicle_type=proposal.vehicle_type,
        vehicle_brand=proposal.vehicle_brand,
        vehicle_model=proposal.vehicle_model,
        vehicle_year=proposal.vehicle_year,
        vehicle_plate=proposal.vehicle_plate,
        meeting_address=proposal.meeting_address,
        meeting_lat=proposal.meeting_lat,
        meeting_lng=proposal.meeting_lng,
        obd_requested=proposal.obd_requested,
        created_at=now,
        expires_at=now + timedelta(hours=PROPOSAL_EXPIRY_HOURS),
    )
    db.add(new_proposal)
    await db.flush()

    # Load mechanic for notification
    mech_result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.id == proposal.mechanic_id).options(selectinload(MechanicProfile.user))
    )
    mechanic = mech_result.scalar_one_or_none()

    # Notify the other party
    if user.role == UserRole.MECHANIC:
        await create_notification(
            db=db,
            user_id=proposal.buyer_id,
            notification_type=NotificationType.PROPOSAL_COUNTER,
            title="Contre-proposition",
            body=f"Le mecanicien propose le {body.proposed_date.strftime('%d/%m')} a {body.proposed_time}.",
            data={"proposal_id": str(new_proposal.id), "type": "proposal_counter"},
        )
    else:
        if mechanic:
            await create_notification(
                db=db,
                user_id=mechanic.user_id,
                notification_type=NotificationType.PROPOSAL_COUNTER,
                title="Contre-proposition",
                body=f"L'acheteur propose le {body.proposed_date.strftime('%d/%m')} a {body.proposed_time}.",
                data={"proposal_id": str(new_proposal.id), "type": "proposal_counter"},
            )

    await db.flush()
    logger.info(
        "proposal_counter",
        old_id=str(proposal.id),
        new_id=str(new_proposal.id),
        round=new_proposal.round_number,
    )

    await _load_proposal_relations(db, new_proposal)
    return _proposal_to_response(
        new_proposal,
        buyer=new_proposal.buyer,
        mechanic_user=new_proposal.mechanic.user if new_proposal.mechanic else None,
    )


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────

async def _get_proposal_for_user(db: AsyncSession, proposal_id: uuid.UUID, user: User) -> DateProposal:
    """Fetch a proposal and verify the user has access."""
    result = await db.execute(
        select(DateProposal)
        .where(DateProposal.id == proposal_id)
        .options(
            selectinload(DateProposal.buyer),
            selectinload(DateProposal.mechanic).selectinload(MechanicProfile.user),
        )
    )
    proposal = result.scalar_one_or_none()
    if not proposal:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Proposal not found")

    # Check access
    if user.role == UserRole.BUYER and proposal.buyer_id != user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your proposal")
    elif user.role == UserRole.MECHANIC:
        mech_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = mech_result.scalar_one_or_none()
        if not profile or proposal.mechanic_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your proposal")

    return proposal


def _verify_responder(proposal: DateProposal, user: User) -> None:
    """Verify the user is the one who should respond (not the one who last proposed)."""
    if proposal.responded_by == "buyer" and user.role == UserRole.BUYER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="It's the mechanic's turn to respond",
        )
    if proposal.responded_by == "mechanic" and user.role == UserRole.MECHANIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="It's the buyer's turn to respond",
        )


async def _load_proposal_relations(db: AsyncSession, proposal: DateProposal) -> None:
    """Ensure buyer and mechanic relations are loaded."""
    if not hasattr(proposal, "_sa_instance_state") or proposal.buyer is None:
        buyer_result = await db.execute(select(User).where(User.id == proposal.buyer_id))
        # Use object.__setattr__ to avoid SA instrumentation issues on loaded relationships
        object.__setattr__(proposal, "buyer", buyer_result.scalar_one_or_none())
    if not hasattr(proposal, "_sa_instance_state") or proposal.mechanic is None:
        mech_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.id == proposal.mechanic_id).options(selectinload(MechanicProfile.user))
        )
        object.__setattr__(proposal, "mechanic", mech_result.scalar_one_or_none())
