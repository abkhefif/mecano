import uuid
from datetime import date, datetime, time, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_mechanic, get_current_user, get_verified_buyer
from app.models.buyer_demand import BuyerDemand, DemandInterest
from app.models.date_proposal import DateProposal
from app.models.enums import DemandStatus, NotificationType, ProposalStatus, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.schemas.demand import DemandCreateRequest, DemandInterestResponse, DemandResponse
from app.services.notifications import create_notification
from app.utils.geo import calculate_distance_km
from app.utils.rate_limit import limiter

logger = structlog.get_logger()
router = APIRouter()


# ────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────


def _demand_to_response(
    demand: BuyerDemand,
    interest_count: int = 0,
    buyer_name: str | None = None,
    distance_km: float | None = None,
) -> DemandResponse:
    resp = DemandResponse.model_validate(demand)
    resp.interest_count = interest_count
    resp.buyer_name = buyer_name
    resp.distance_km = distance_km
    return resp


def _interest_to_response(
    interest: DemandInterest,
    mechanic_name: str | None = None,
    mechanic_city: str | None = None,
    mechanic_rating: float | None = None,
) -> DemandInterestResponse:
    resp = DemandInterestResponse.model_validate(interest)
    resp.mechanic_name = mechanic_name
    resp.mechanic_city = mechanic_city
    resp.mechanic_rating = mechanic_rating
    return resp


def _end_of_day_utc(d: date) -> datetime:
    """Return the end-of-day datetime (23:59:59) for a given date in UTC."""
    return datetime(d.year, d.month, d.day, 23, 59, 59, tzinfo=timezone.utc)


# ────────────────────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────────────────────


@router.post("", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_demand(
    request: Request,
    body: DemandCreateRequest,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
) -> DemandResponse:
    """Buyer creates a reverse-booking demand.

    Nearby active and verified mechanics are automatically notified.
    """
    now = datetime.now(timezone.utc)
    desired_date = body.desired_date

    # Validate the desired date is not in the past
    today = date.today()
    if desired_date < today:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="desired_date must not be in the past",
        )

    demand = BuyerDemand(
        buyer_id=buyer.id,
        vehicle_type=body.vehicle_type,
        vehicle_brand=body.vehicle_brand,
        vehicle_model=body.vehicle_model,
        vehicle_year=body.vehicle_year,
        vehicle_plate=body.vehicle_plate,
        meeting_address=body.meeting_address,
        meeting_lat=body.meeting_lat,
        meeting_lng=body.meeting_lng,
        desired_date=desired_date,
        start_time=time.fromisoformat(body.start_time),
        end_time=time.fromisoformat(body.end_time),
        obd_requested=body.obd_requested,
        message=body.message,
        status=DemandStatus.OPEN,
        created_at=now,
        expires_at=_end_of_day_utc(desired_date),
    )
    db.add(demand)
    await db.flush()

    # Fetch all active, verified mechanics
    mechanics_result = await db.execute(
        select(MechanicProfile).where(
            MechanicProfile.is_active == True,  # noqa: E712
            MechanicProfile.is_identity_verified == True,  # noqa: E712
        )
    )
    mechanics = mechanics_result.scalars().all()

    notified_count = 0
    for mechanic in mechanics:
        # Skip mechanics without coordinates
        if mechanic.city_lat is None or mechanic.city_lng is None:
            continue

        # Check vehicle type compatibility
        if body.vehicle_type.value not in mechanic.accepted_vehicle_types:
            continue

        # Check distance
        dist_km = calculate_distance_km(
            float(mechanic.city_lat),
            float(mechanic.city_lng),
            body.meeting_lat,
            body.meeting_lng,
        )
        if dist_km > mechanic.max_radius_km:
            continue

        await create_notification(
            db=db,
            user_id=mechanic.user_id,
            notification_type=NotificationType.DEMAND_NEARBY,
            title="Nouvelle demande d'inspection proche",
            body=(
                f"Un acheteur cherche un mecanicien le "
                f"{desired_date.strftime('%d/%m')} entre "
                f"{body.start_time} et {body.end_time} "
                f"pour un {body.vehicle_brand} {body.vehicle_model}."
            ),
            data={"demand_id": str(demand.id), "type": "demand_nearby"},
        )
        notified_count += 1

    await db.flush()
    logger.info(
        "demand_created",
        demand_id=str(demand.id),
        buyer_id=str(buyer.id),
        mechanics_notified=notified_count,
    )

    buyer_name = buyer.first_name or buyer.email.split("@")[0]
    return _demand_to_response(demand, interest_count=0, buyer_name=buyer_name)


@router.get("/mine")
@limiter.limit("30/minute")
async def list_my_demands(
    request: Request,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
) -> list[DemandResponse]:
    """Buyer lists all their own demands, ordered by creation date descending."""
    # Subquery: count interests per demand
    interest_count_sq = (
        select(
            DemandInterest.demand_id,
            func.count(DemandInterest.id).label("cnt"),
        )
        .group_by(DemandInterest.demand_id)
        .subquery()
    )

    result = await db.execute(
        select(BuyerDemand, interest_count_sq.c.cnt)
        .outerjoin(interest_count_sq, BuyerDemand.id == interest_count_sq.c.demand_id)
        .where(BuyerDemand.buyer_id == buyer.id)
        .order_by(BuyerDemand.created_at.desc())
    )
    rows = result.all()

    buyer_name = buyer.first_name or buyer.email.split("@")[0]
    return [
        _demand_to_response(demand, interest_count=cnt or 0, buyer_name=buyer_name)
        for demand, cnt in rows
    ]


@router.get("/nearby")
@limiter.limit("30/minute")
async def list_nearby_demands(
    request: Request,
    mechanic_data: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
) -> list[DemandResponse]:
    """Mechanic sees open demands within their service radius and accepted vehicle types."""
    _, mechanic_profile = mechanic_data

    today = date.today()
    now = datetime.now(timezone.utc)

    # Fetch open, non-expired demands with a future or current desired_date
    result = await db.execute(
        select(BuyerDemand).where(
            BuyerDemand.status == DemandStatus.OPEN,
            BuyerDemand.expires_at > now,
            BuyerDemand.desired_date >= today,
        )
    )
    demands = result.scalars().all()

    # If mechanic has no coordinates, return empty list (cannot compute distance)
    if mechanic_profile.city_lat is None or mechanic_profile.city_lng is None:
        return []

    mechanic_lat = float(mechanic_profile.city_lat)
    mechanic_lng = float(mechanic_profile.city_lng)

    filtered: list[DemandResponse] = []
    for demand in demands:
        # Vehicle type filter
        if demand.vehicle_type.value not in mechanic_profile.accepted_vehicle_types:
            continue

        dist_km = calculate_distance_km(
            mechanic_lat,
            mechanic_lng,
            float(demand.meeting_lat),
            float(demand.meeting_lng),
        )
        if dist_km > mechanic_profile.max_radius_km:
            continue

        filtered.append(
            _demand_to_response(demand, distance_km=round(dist_km, 2))
        )

    return filtered


@router.get("/{demand_id}")
@limiter.limit("30/minute")
async def get_demand(
    request: Request,
    demand_id: uuid.UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Detail view for a demand.

    - Buyer: sees their demand with all interests (mechanic info included).
    - Mechanic: sees the demand and their own interest status (if any).
    """
    result = await db.execute(
        select(BuyerDemand)
        .where(BuyerDemand.id == demand_id)
        .options(
            selectinload(BuyerDemand.buyer),
            selectinload(BuyerDemand.interests).selectinload(DemandInterest.mechanic).selectinload(MechanicProfile.user),
        )
    )
    demand = result.scalar_one_or_none()
    if not demand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demand not found")

    if user.role == UserRole.BUYER:
        if demand.buyer_id != user.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your demand")

        buyer_name = demand.buyer.first_name or demand.buyer.email.split("@")[0]
        demand_resp = _demand_to_response(
            demand,
            interest_count=len(demand.interests),
            buyer_name=buyer_name,
        )

        interests_resp = [
            _interest_to_response(
                interest,
                mechanic_name=(
                    interest.mechanic.user.first_name or interest.mechanic.user.email.split("@")[0]
                    if interest.mechanic and interest.mechanic.user
                    else None
                ),
                mechanic_city=interest.mechanic.city if interest.mechanic else None,
                mechanic_rating=float(interest.mechanic.rating_avg) if interest.mechanic else None,
            )
            for interest in demand.interests
        ]
        return {"demand": demand_resp, "interests": interests_resp}

    elif user.role == UserRole.MECHANIC:
        mech_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        mechanic_profile = mech_result.scalar_one_or_none()
        if not mechanic_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic profile not found"
            )

        # Find own interest if any
        own_interest = next(
            (i for i in demand.interests if i.mechanic_id == mechanic_profile.id), None
        )

        dist_km: float | None = None
        if mechanic_profile.city_lat is not None and mechanic_profile.city_lng is not None:
            dist_km = round(
                calculate_distance_km(
                    float(mechanic_profile.city_lat),
                    float(mechanic_profile.city_lng),
                    float(demand.meeting_lat),
                    float(demand.meeting_lng),
                ),
                2,
            )

        if own_interest is None:
            if dist_km is None or dist_km > float(mechanic_profile.max_radius_km):
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Demand is outside your service area")

        demand_resp = _demand_to_response(demand, distance_km=dist_km)
        own_interest_resp = (
            _interest_to_response(own_interest) if own_interest else None
        )
        return {"demand": demand_resp, "my_interest": own_interest_resp}

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not authorized")


@router.post("/{demand_id}/interest", status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def express_interest(
    request: Request,
    demand_id: uuid.UUID,
    mechanic_data: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
) -> DemandInterestResponse:
    """Mechanic expresses interest in a buyer demand.

    Automatically creates a DateProposal and notifies the buyer.
    """
    mechanic_user, mechanic_profile = mechanic_data

    # Fetch the demand
    result = await db.execute(
        select(BuyerDemand).where(BuyerDemand.id == demand_id)
    )
    demand = result.scalar_one_or_none()
    if not demand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demand not found")

    now = datetime.now(timezone.utc)

    # Validate demand is open
    if demand.status != DemandStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demand is no longer open",
        )

    # Validate demand has not expired
    if demand.expires_at <= now:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demand has expired",
        )

    # Validate vehicle type compatibility
    if demand.vehicle_type.value not in mechanic_profile.accepted_vehicle_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You do not accept this vehicle type",
        )

    # Validate mechanic is within radius
    if mechanic_profile.city_lat is None or mechanic_profile.city_lng is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Mechanic location is not configured",
        )

    dist_km = calculate_distance_km(
        float(mechanic_profile.city_lat),
        float(mechanic_profile.city_lng),
        float(demand.meeting_lat),
        float(demand.meeting_lng),
    )
    if dist_km > mechanic_profile.max_radius_km:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Demand location is outside your service radius",
        )

    # Check for duplicate interest
    existing_result = await db.execute(
        select(DemandInterest).where(
            DemandInterest.demand_id == demand_id,
            DemandInterest.mechanic_id == mechanic_profile.id,
        )
    )
    if existing_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already expressed interest in this demand",
        )

    # Auto-create a DateProposal for the buyer
    proposal = DateProposal(
        buyer_id=demand.buyer_id,
        mechanic_id=mechanic_profile.id,
        proposed_date=demand.desired_date,
        proposed_time=demand.start_time.strftime("%H:%M"),
        message=None,
        status=ProposalStatus.PENDING,
        round_number=1,
        responded_by="mechanic",
        vehicle_type=demand.vehicle_type,
        vehicle_brand=demand.vehicle_brand,
        vehicle_model=demand.vehicle_model,
        vehicle_year=demand.vehicle_year,
        vehicle_plate=demand.vehicle_plate,
        meeting_address=demand.meeting_address,
        meeting_lat=demand.meeting_lat,
        meeting_lng=demand.meeting_lng,
        obd_requested=demand.obd_requested,
        created_at=now,
        expires_at=now + timedelta(hours=48),
    )
    db.add(proposal)
    await db.flush()

    # Create DemandInterest linked to the proposal
    interest = DemandInterest(
        demand_id=demand.id,
        mechanic_id=mechanic_profile.id,
        proposal_id=proposal.id,
        created_at=now,
    )
    db.add(interest)
    await db.flush()

    # Notify buyer
    mechanic_display = mechanic_user.first_name or mechanic_user.email.split("@")[0]
    await create_notification(
        db=db,
        user_id=demand.buyer_id,
        notification_type=NotificationType.MECHANIC_INTERESTED,
        title="Un mecanicien est interesse",
        body=(
            f"{mechanic_display} souhaite inspecter votre "
            f"{demand.vehicle_brand} {demand.vehicle_model} "
            f"le {demand.desired_date.strftime('%d/%m')}."
        ),
        data={
            "demand_id": str(demand.id),
            "proposal_id": str(proposal.id),
            "type": "mechanic_interested",
        },
    )

    await db.flush()
    logger.info(
        "demand_interest_created",
        demand_id=str(demand.id),
        mechanic_id=str(mechanic_profile.id),
        proposal_id=str(proposal.id),
    )

    return _interest_to_response(
        interest,
        mechanic_name=mechanic_display,
        mechanic_city=mechanic_profile.city,
        mechanic_rating=float(mechanic_profile.rating_avg),
    )


@router.patch("/{demand_id}/close")
@limiter.limit("10/minute")
async def close_demand(
    request: Request,
    demand_id: uuid.UUID,
    buyer: User = Depends(get_verified_buyer),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Buyer closes a demand manually."""
    result = await db.execute(
        select(BuyerDemand).where(BuyerDemand.id == demand_id)
    )
    demand = result.scalar_one_or_none()
    if not demand:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demand not found")

    if demand.buyer_id != buyer.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your demand")

    if demand.status != DemandStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Demand is already closed or expired",
        )

    demand.status = DemandStatus.CLOSED
    await db.flush()
    logger.info("demand_closed", demand_id=str(demand.id), buyer_id=str(buyer.id))

    return {"status": "closed", "demand_id": str(demand.id)}
