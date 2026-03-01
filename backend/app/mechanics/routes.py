import uuid
from datetime import date, datetime, time, timedelta, timezone
from math import cos, radians

import structlog
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, UploadFile, status
from sqlalchemy import and_, cast, func, or_, select, String
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_mechanic, get_current_user
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
    offset: int = Query(0, ge=0, le=10000),
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
        .limit(200)  # AUD-M10: Reduced from 500 to 200 to limit memory usage
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

        if profile.city_lat is None or profile.city_lng is None:
            continue

        dist = calculate_distance_km(lat, lng, profile.city_lat, profile.city_lng)
        if dist > radius_km or dist > profile.max_radius_km:
            continue

        item = MechanicListItem(
            id=profile.id,
            user_id=profile.user_id,
            city=profile.city,
            city_lat=round(float(profile.city_lat), 1),
            city_lng=round(float(profile.city_lng), 1),
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
            service_location=profile.service_location,
            garage_address=profile.garage_address,
        )
        mechanics.append(item)

    mechanics.sort(key=lambda m: m.distance_km or 0)
    # Pagination: offset/limit are applied after in-memory distance filtering
    # because the SQL bounding box is a coarse pre-filter. The 500-row SQL cap
    # bounds memory usage while the Python slice provides true pagination.
    return mechanics[offset:offset + limit]


@router.get("/me/stats")
@limiter.limit("30/minute")
async def get_my_stats(
    request: Request,
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
@limiter.limit("30/minute")
async def update_mechanic_profile(
    request: Request,
    body: MechanicUpdateRequest,
    mechanic: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Update the current mechanic's profile."""
    _, profile = mechanic

    UPDATABLE_FIELDS = {"city", "city_lat", "city_lng", "max_radius_km", "free_zone_km", "accepted_vehicle_types", "has_obd_diagnostic", "service_location", "garage_address"}

    update_data = body.model_dump(exclude_unset=True)
    if "accepted_vehicle_types" in update_data and update_data["accepted_vehicle_types"] is not None:
        update_data["accepted_vehicle_types"] = [v.value for v in update_data["accepted_vehicle_types"]]
    if "service_location" in update_data and update_data["service_location"] is not None:
        update_data["service_location"] = update_data["service_location"].value

    for field, value in update_data.items():
        if field in UPDATABLE_FIELDS:
            setattr(profile, field, value)

    # BUG-012: Validate free_zone_km <= max_radius_km using current DB values
    # The schema validator only checks when BOTH fields are in the same request.
    if profile.free_zone_km > profile.max_radius_km:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="free_zone_km must be less than or equal to max_radius_km",
        )

    await db.flush()
    logger.info("mechanic_profile_updated", mechanic_id=str(profile.id))

    return MechanicDetailResponse.model_validate(profile)


@router.post("/me/identity", status_code=status.HTTP_200_OK)
@limiter.limit("10/minute")
async def upload_identity_documents(
    request: Request,
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
@limiter.limit("10/minute")
async def upload_profile_photo(
    request: Request,
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
@limiter.limit("10/minute")
async def upload_cv(
    request: Request,
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
@limiter.limit("10/minute")
async def create_diploma(
    request: Request,
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
@limiter.limit("30/minute")
async def delete_diploma(
    request: Request,
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
@limiter.limit("30/minute")
async def create_availability(
    request: Request,
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

    # AUD-027: Limit unbooked availability slots per mechanic to prevent abuse
    slot_count_result = await db.execute(
        select(func.count()).where(
            Availability.mechanic_id == profile.id,
            Availability.is_booked == False,
        )
    )
    slot_count = slot_count_result.scalar() or 0
    if slot_count >= 100:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 100 unbooked availability slots allowed",
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
@limiter.limit(LIST_RATE_LIMIT)
async def list_availabilities(
    request: Request,
    mechanic_id: uuid.UUID = Query(...),
    date_from: date = Query(...),
    date_to: date = Query(...),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    _user: User = Depends(get_current_user),  # HIGH-01: Require authentication to prevent unauthenticated schedule enumeration
):
    """List available (non-booked) slots for a mechanic in a date range."""
    if (date_to - date_from).days > 90:
        raise HTTPException(status_code=400, detail="Date range cannot exceed 90 days")

    now = datetime.now(timezone.utc)
    today_date = now.date()
    now_time = now.time()

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
        .limit(limit)
    )
    return [AvailabilityResponse.model_validate(a) for a in result.scalars().all()]


@router.delete("/availabilities/{availability_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("30/minute")
async def delete_availability(
    request: Request,
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
@limiter.limit(LIST_RATE_LIMIT)
async def get_mechanic(
    request: Request,
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

    # BUG-008: Diplomas — exclude document_url from public response
    diploma_result = await db.execute(
        select(Diploma)
        .where(Diploma.mechanic_id == mechanic_id)
        .order_by(Diploma.created_at.desc())
    )
    diplomas = [
        DiplomaResponse(
            id=d.id,
            name=d.name,
            year=d.year,
            document_url=None,
            created_at=d.created_at,
        )
        for d in diploma_result.scalars().all()
    ]

    # Availabilities for next 7 days (exclude past slots)
    now = datetime.now(timezone.utc)
    today = now.date()
    now_time = now.time()
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

    # R-001: Public endpoint must not expose cv_url (personal document).
    # has_cv is still returned so the mobile UI can show a badge.
    return MechanicDetailWithSlots(
        profile=MechanicDetailResponse(
            id=profile.id,
            user_id=profile.user_id,
            city=profile.city,
            city_lat=round(float(profile.city_lat), 1) if profile.city_lat is not None else None,
            city_lng=round(float(profile.city_lng), 1) if profile.city_lng is not None else None,
            max_radius_km=profile.max_radius_km,
            free_zone_km=profile.free_zone_km,
            accepted_vehicle_types=profile.accepted_vehicle_types,
            rating_avg=profile.rating_avg,
            total_reviews=profile.total_reviews,
            has_cv=profile.has_cv,
            has_obd_diagnostic=profile.has_obd_diagnostic,
            is_identity_verified=profile.is_identity_verified,
            photo_url=profile.photo_url,
            cv_url=None,
            service_location=profile.service_location,
            garage_address=profile.garage_address,
        ),
        reviews=reviews,
        availabilities=availabilities,
        diplomas=diplomas,
    )
