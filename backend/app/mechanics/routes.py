import uuid
from datetime import date, datetime, time, timedelta, timezone
from math import cos, radians

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_mechanic
from app.models.availability import Availability
from app.models.mechanic_profile import MechanicProfile
from app.models.review import Review
from app.models.user import User
from app.schemas.mechanic import (
    AvailabilityCreateRequest,
    AvailabilityResponse,
    MechanicDetailResponse,
    MechanicDetailWithSlots,
    MechanicListItem,
    MechanicUpdateRequest,
    ReviewSummary,
)
from app.services.storage import upload_file
from app.utils.geo import calculate_distance_km

logger = structlog.get_logger()
router = APIRouter()


# --- Static routes first (before /{mechanic_id}) ---


@router.get("", response_model=list[MechanicListItem])
async def list_mechanics(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: int = Query(50, ge=1, le=200),
    vehicle_type: str = Query("car"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Search for verified mechanics near a location."""
    # Bounding-box pre-filter: 1 degree latitude ≈ 111 km
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(cos(radians(lat)), 0.01))

    # Build query with vehicle_type filter for SQL performance
    from sqlalchemy import cast, String
    stmt = select(MechanicProfile).where(
        MechanicProfile.is_identity_verified == True,
        MechanicProfile.is_active == True,
        MechanicProfile.city_lat >= lat - lat_delta,
        MechanicProfile.city_lat <= lat + lat_delta,
        MechanicProfile.city_lng >= lng - lng_delta,
        MechanicProfile.city_lng <= lng + lng_delta,
        cast(MechanicProfile.accepted_vehicle_types, String).contains(vehicle_type),
    ).limit(500)

    result = await db.execute(stmt)
    profiles = result.scalars().all()

    if not profiles:
        return []

    # Fetch next available date per mechanic (unbooked, future slots)
    now = datetime.now(timezone.utc)
    today_date = now.date()
    now_time = now.time()
    profile_ids = [p.id for p in profiles]

    # Exclude past slots: future dates OR today with start_time still in the future
    from sqlalchemy import or_
    avail_stmt = (
        select(
            Availability.mechanic_id,
            func.min(Availability.date).label("next_date"),
        )
        .where(
            Availability.mechanic_id.in_(profile_ids),
            Availability.is_booked == False,
            or_(
                Availability.date > today_date,
                and_(Availability.date == today_date, Availability.start_time > now_time),
            ),
        )
        .group_by(Availability.mechanic_id)
    )
    avail_result = await db.execute(avail_stmt)
    next_dates: dict[uuid.UUID, date] = {
        row.mechanic_id: row.next_date for row in avail_result
    }

    mechanics = []
    for profile in profiles:
        if vehicle_type not in profile.accepted_vehicle_types:
            continue

        # Only include mechanics with at least one future available slot
        if profile.id not in next_dates:
            continue

        dist = calculate_distance_km(lat, lng, profile.city_lat, profile.city_lng)
        if dist > radius_km or dist > profile.max_radius_km:
            continue

        item = MechanicListItem(
            id=profile.id,
            user_id=profile.user_id,
            city=profile.city,
            city_lat=profile.city_lat,
            city_lng=profile.city_lng,
            distance_km=round(dist, 1),
            max_radius_km=profile.max_radius_km,
            accepted_vehicle_types=profile.accepted_vehicle_types,
            rating_avg=profile.rating_avg,
            total_reviews=profile.total_reviews,
            has_cv=profile.has_cv,
            is_identity_verified=profile.is_identity_verified,
            next_available_date=next_dates[profile.id].isoformat(),
        )
        mechanics.append(item)

    mechanics.sort(key=lambda m: m.distance_km or 0)
    return mechanics[offset:offset + limit]


@router.put("/me", response_model=MechanicDetailResponse)
async def update_mechanic_profile(
    body: MechanicUpdateRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Update the current mechanic's profile."""
    _, profile = mechanic

    UPDATABLE_FIELDS = {"city", "city_lat", "city_lng", "max_radius_km", "free_zone_km", "accepted_vehicle_types"}

    update_data = body.model_dump(exclude_unset=True)
    if "accepted_vehicle_types" in update_data and update_data["accepted_vehicle_types"] is not None:
        update_data["accepted_vehicle_types"] = [v.value for v in update_data["accepted_vehicle_types"]]

    for field, value in update_data.items():
        if field in UPDATABLE_FIELDS:
            setattr(profile, field, value)

    await db.flush()
    logger.info("mechanic_profile_updated", mechanic_id=str(profile.id))

    return MechanicDetailResponse.model_validate(profile)


@router.post("/me/identity", status_code=status.HTTP_200_OK)
async def upload_identity_documents(
    identity_document: UploadFile,
    selfie_with_id: UploadFile,
    cv: UploadFile | None = None,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Upload identity verification documents."""
    _, profile = mechanic

    try:
        id_url = await upload_file(identity_document, "identity")
        selfie_url = await upload_file(selfie_with_id, "identity")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    profile.identity_document_url = id_url
    profile.selfie_with_id_url = selfie_url
    profile.is_identity_verified = False  # Awaiting admin review

    if cv:
        try:
            cv_url = await upload_file(cv, "cv")
            profile.cv_url = cv_url
            profile.has_cv = True
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    await db.flush()
    logger.info("identity_documents_uploaded", mechanic_id=str(profile.id))

    return {"status": "uploaded", "message": "Documents uploaded. Awaiting admin verification."}


# --- Availabilities (static paths before dynamic) ---


@router.post("/availabilities", response_model=AvailabilityResponse, status_code=status.HTTP_201_CREATED)
async def create_availability(
    body: AvailabilityCreateRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Create a new availability slot."""
    _, profile = mechanic

    if not profile.is_identity_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Identity must be verified before creating availability slots",
        )

    if body.end_time <= body.start_time:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="End time must be after start time",
        )

    # Check for overlap
    overlap_result = await db.execute(
        select(Availability).where(
            Availability.mechanic_id == profile.id,
            Availability.date == body.date,
            Availability.start_time < body.end_time,
            Availability.end_time > body.start_time,
        ).with_for_update()
    )
    if overlap_result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This slot overlaps with an existing availability",
        )

    availability = Availability(
        mechanic_id=profile.id,
        date=body.date,
        start_time=body.start_time,
        end_time=body.end_time,
    )
    db.add(availability)
    await db.flush()

    logger.info("availability_created", availability_id=str(availability.id))
    return AvailabilityResponse.model_validate(availability)


@router.get("/availabilities", response_model=list[AvailabilityResponse])
async def list_availabilities(
    mechanic_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """List available (non-booked) slots for a mechanic in a date range."""
    now = datetime.now(timezone.utc)
    today_date = now.date()
    now_time = now.time()

    from sqlalchemy import or_
    result = await db.execute(
        select(Availability).where(
            Availability.mechanic_id == mechanic_id,
            Availability.is_booked == False,
            Availability.date >= date_from,
            Availability.date <= date_to,
            # Exclude past slots
            or_(
                Availability.date > today_date,
                and_(Availability.date == today_date, Availability.start_time > now_time),
            ),
        ).order_by(Availability.date, Availability.start_time)
    )
    return [AvailabilityResponse.model_validate(a) for a in result.scalars().all()]


@router.delete("/availabilities/{availability_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_availability(
    availability_id: uuid.UUID,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Delete an unbooked availability slot."""
    _, profile = mechanic

    result = await db.execute(
        select(Availability).where(
            Availability.id == availability_id,
            Availability.mechanic_id == profile.id,
        )
    )
    availability = result.scalar_one_or_none()
    if not availability:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Availability not found")

    if availability.is_booked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete a booked slot",
        )

    await db.delete(availability)
    await db.flush()


# --- Dynamic route last ---


@router.get("/{mechanic_id}", response_model=MechanicDetailWithSlots)
async def get_mechanic(
    mechanic_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed mechanic profile with reviews and upcoming availability."""
    result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.id == mechanic_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic not found")

    # Last 5 public reviews
    review_result = await db.execute(
        select(Review)
        .where(Review.reviewee_id == profile.user_id, Review.is_public == True)
        .order_by(Review.created_at.desc())
        .limit(5)
    )
    reviews = [
        ReviewSummary(
            id=r.id,
            rating=r.rating,
            comment=r.comment,
            created_at=r.created_at,
        )
        for r in review_result.scalars().all()
    ]

    # Availabilities for next 7 days (exclude past slots)
    now = datetime.now(timezone.utc)
    today = now.date()
    now_time = now.time()
    from sqlalchemy import or_
    avail_result = await db.execute(
        select(Availability).where(
            Availability.mechanic_id == mechanic_id,
            Availability.is_booked == False,
            Availability.date >= today,
            Availability.date <= today + timedelta(days=7),
            or_(
                Availability.date > today,
                and_(Availability.date == today, Availability.start_time > now_time),
            ),
        ).order_by(Availability.date, Availability.start_time)
    )
    availabilities = [
        AvailabilityResponse.model_validate(a) for a in avail_result.scalars().all()
    ]

    return MechanicDetailWithSlots(
        profile=MechanicDetailResponse(
            id=profile.id,
            user_id=profile.user_id,
            city=profile.city,
            city_lat=profile.city_lat,
            city_lng=profile.city_lng,
            max_radius_km=profile.max_radius_km,
            free_zone_km=profile.free_zone_km,
            accepted_vehicle_types=profile.accepted_vehicle_types,
            rating_avg=profile.rating_avg,
            total_reviews=profile.total_reviews,
            has_cv=profile.has_cv,
            is_identity_verified=profile.is_identity_verified,
        ),
        reviews=reviews,
        availabilities=availabilities,
    )
