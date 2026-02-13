import uuid
from datetime import date, datetime, time, timedelta, timezone
from math import cos, radians

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_mechanic
from app.models.availability import Availability
from app.models.diploma import Diploma
from app.models.enums import VehicleType
from app.models.mechanic_profile import MechanicProfile
from app.models.review import Review
from app.models.user import User
from app.schemas.mechanic import (
    AvailabilityCreateRequest,
    AvailabilityResponse,
    DiplomaResponse,
    MechanicDetailResponse,
    MechanicDetailWithSlots,
    MechanicListItem,
    MechanicUpdateRequest,
    ReviewSummary,
)
from app.services.storage import upload_file
from app.utils.geo import calculate_distance_km
from app.utils.rate_limit import LIST_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()


# --- Static routes first (before /{mechanic_id}) ---


@router.get("", response_model=list[MechanicListItem])
@limiter.limit(LIST_RATE_LIMIT)
async def list_mechanics(
    request: Request,
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_km: int = Query(50, ge=1, le=200),
    vehicle_type: VehicleType = Query(VehicleType.CAR),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Search for verified mechanics near a location.

    The query uses a bounding-box pre-filter and is capped at 500 rows to keep
    response times bounded even for large geographic areas.  Client-side
    pagination is applied via ``limit``/``offset`` *after* Python-side distance
    filtering, so the 500-record SQL cap is intentional — it covers the
    worst-case bounding box while preventing full table scans.

    SEC-024: This endpoint returns exact GPS coordinates (city_lat/city_lng).
    This is by design — buyers need to see mechanic locations on a map to
    choose a nearby mechanic. Consider returning approximate coordinates
    (e.g. rounded to ~1 km precision) in a future iteration.
    """
    # Bounding-box pre-filter: 1 degree latitude ≈ 111 km
    lat_delta = radius_km / 111.0
    lng_delta = radius_km / (111.0 * max(cos(radians(lat)), 0.01))

    # Build query with vehicle_type filter for SQL performance.
    # selectinload(MechanicProfile.user) eagerly loads the related User in a
    # single extra SELECT, avoiding N+1 queries when serialising the response.
    from sqlalchemy import cast, String
    stmt = (
        select(MechanicProfile)
        .options(selectinload(MechanicProfile.user))
        .where(
            MechanicProfile.is_identity_verified == True,
            MechanicProfile.is_active == True,
            MechanicProfile.city_lat >= lat - lat_delta,
            MechanicProfile.city_lat <= lat + lat_delta,
            MechanicProfile.city_lng >= lng - lng_delta,
            MechanicProfile.city_lng <= lng + lng_delta,
            cast(MechanicProfile.accepted_vehicle_types, String).contains(vehicle_type.value),
        )
        .limit(500)  # Intentional hard cap — see docstring
    )

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
                and_(Availability.date == today_date, Availability.end_time > now_time),
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
        if vehicle_type.value not in profile.accepted_vehicle_types:
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
            city_lat=round(float(profile.city_lat), 2),
            city_lng=round(float(profile.city_lng), 2),
            distance_km=round(dist, 1),
            max_radius_km=profile.max_radius_km,
            accepted_vehicle_types=profile.accepted_vehicle_types,
            rating_avg=profile.rating_avg,
            total_reviews=profile.total_reviews,
            has_cv=profile.has_cv,
            has_obd_diagnostic=profile.has_obd_diagnostic,
            is_identity_verified=profile.is_identity_verified,
            photo_url=profile.photo_url,
            next_available_date=next_dates[profile.id].isoformat(),
        )
        mechanics.append(item)

    mechanics.sort(key=lambda m: m.distance_km or 0)
    # Pagination: offset/limit are applied after in-memory distance filtering
    # because the SQL bounding box is a coarse pre-filter. The 500-row SQL cap
    # bounds memory usage while the Python slice provides true pagination.
    return mechanics[offset:offset + limit]


@router.get("/me/stats")
async def get_my_stats(
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Return performance statistics for the current mechanic."""
    _, profile = mechanic

    from app.models.booking import Booking
    from app.models.enums import BookingStatus

    # Total completed missions and earnings
    total_result = await db.execute(
        select(func.count(Booking.id), func.coalesce(func.sum(Booking.mechanic_payout), 0))
        .where(Booking.mechanic_id == profile.id, Booking.status == BookingStatus.COMPLETED)
    )
    total_missions, total_earnings = total_result.one()

    # This month stats
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_result = await db.execute(
        select(func.count(Booking.id), func.coalesce(func.sum(Booking.mechanic_payout), 0))
        .where(
            Booking.mechanic_id == profile.id,
            Booking.status == BookingStatus.COMPLETED,
            Booking.created_at >= month_start,
        )
    )
    month_missions, month_earnings = month_result.one()

    # M-08: Acceptance rate = accepted / (accepted + refused_by_mechanic)
    # Excludes buyer-cancelled bookings from the denominator
    accepted_result = await db.execute(
        select(func.count(Booking.id))
        .where(
            Booking.mechanic_id == profile.id,
            Booking.status.notin_([BookingStatus.PENDING_ACCEPTANCE, BookingStatus.CANCELLED]),
        )
    )
    accepted_count = accepted_result.scalar() or 0

    refused_by_mechanic_result = await db.execute(
        select(func.count(Booking.id))
        .where(
            Booking.mechanic_id == profile.id,
            Booking.status == BookingStatus.CANCELLED,
            Booking.cancelled_by == "mechanic",
        )
    )
    refused_count = refused_by_mechanic_result.scalar() or 0

    denominator = accepted_count + refused_count
    acceptance_rate = (
        round((accepted_count / denominator * 100), 1)
        if denominator > 0
        else 100.0
    )

    return {
        "total_missions": total_missions,
        "total_earnings": float(total_earnings),
        "this_month_missions": month_missions,
        "this_month_earnings": float(month_earnings),
        "average_rating": float(profile.rating_avg),
        "total_reviews": profile.total_reviews,
        "acceptance_rate": acceptance_rate,
    }


@router.put("/me", response_model=MechanicDetailResponse)
async def update_mechanic_profile(
    body: MechanicUpdateRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Update the current mechanic's profile."""
    _, profile = mechanic

    UPDATABLE_FIELDS = {"city", "city_lat", "city_lng", "max_radius_km", "free_zone_km", "accepted_vehicle_types", "has_obd_diagnostic"}

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


@router.post("/me/photo", status_code=status.HTTP_200_OK)
async def upload_profile_photo(
    photo: UploadFile,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Upload or replace the mechanic's profile photo."""
    _, profile = mechanic
    try:
        photo_url = await upload_file(photo, "avatars")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    profile.photo_url = photo_url
    await db.flush()
    logger.info("profile_photo_uploaded", mechanic_id=str(profile.id))
    return {"photo_url": photo_url}


@router.post("/me/cv", status_code=status.HTTP_200_OK)
async def upload_cv(
    cv: UploadFile,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Upload or replace the mechanic's CV."""
    _, profile = mechanic
    try:
        cv_url = await upload_file(cv, "cv")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    profile.cv_url = cv_url
    profile.has_cv = True
    await db.flush()
    logger.info("cv_uploaded", mechanic_id=str(profile.id))
    return {"cv_url": cv_url, "has_cv": True}


@router.post("/me/diplomas", status_code=status.HTTP_201_CREATED)
async def create_diploma(
    name: str = Form(..., max_length=255),
    year: int | None = Form(None),
    document: UploadFile | None = None,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Add a diploma to the mechanic's profile."""
    _, profile = mechanic

    document_url = None
    if document:
        try:
            document_url = await upload_file(document, "diplomas")
        except ValueError as e:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    diploma = Diploma(
        mechanic_id=profile.id,
        name=name,
        year=year,
        document_url=document_url,
    )
    db.add(diploma)
    await db.flush()

    logger.info("diploma_created", diploma_id=str(diploma.id), mechanic_id=str(profile.id))
    return DiplomaResponse.model_validate(diploma)


@router.delete("/me/diplomas/{diploma_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_diploma(
    diploma_id: uuid.UUID,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Delete a diploma from the mechanic's profile."""
    _, profile = mechanic

    result = await db.execute(
        select(Diploma).where(
            Diploma.id == diploma_id,
            Diploma.mechanic_id == profile.id,
        )
    )
    diploma = result.scalar_one_or_none()
    if not diploma:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Diploma not found")

    await db.delete(diploma)
    await db.flush()

    logger.info("diploma_deleted", diploma_id=str(diploma_id), mechanic_id=str(profile.id))


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
                and_(Availability.date == today_date, Availability.end_time > now_time),
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

    # Diplomas
    diploma_result = await db.execute(
        select(Diploma)
        .where(Diploma.mechanic_id == mechanic_id)
        .order_by(Diploma.created_at.desc())
    )
    diplomas = [
        DiplomaResponse.model_validate(d) for d in diploma_result.scalars().all()
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
                and_(Availability.date == today, Availability.end_time > now_time),
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
            city_lat=round(float(profile.city_lat), 2),
            city_lng=round(float(profile.city_lng), 2),
            max_radius_km=profile.max_radius_km,
            free_zone_km=profile.free_zone_km,
            accepted_vehicle_types=profile.accepted_vehicle_types,
            rating_avg=profile.rating_avg,
            total_reviews=profile.total_reviews,
            has_cv=profile.has_cv,
            has_obd_diagnostic=profile.has_obd_diagnostic,
            is_identity_verified=profile.is_identity_verified,
            photo_url=profile.photo_url,
            cv_url=profile.cv_url,
        ),
        reviews=reviews,
        availabilities=availabilities,
        diplomas=diplomas,
    )
