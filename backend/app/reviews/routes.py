import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_user
from app.models.booking import Booking
from app.models.enums import BookingStatus, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.review import Review
from app.models.user import User
from app.schemas.review import ReviewCreateRequest, ReviewResponse
from app.utils.rate_limit import LIST_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()


@router.post("", response_model=ReviewResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_review(
    request: Request,
    body: ReviewCreateRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a review for a completed booking."""
    # Fetch booking with mechanic relationship for reviewee lookup
    result = await db.execute(
        select(Booking)
        .where(Booking.id == body.booking_id)
        .options(selectinload(Booking.mechanic))
    )
    booking = result.scalar_one_or_none()
    if not booking:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Booking not found")

    if booking.status != BookingStatus.COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Can only review completed bookings",
        )

    # Check existing review
    existing = await db.execute(
        select(Review).where(Review.booking_id == booking.id, Review.reviewer_id == user.id)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already reviewed this booking")

    # Determine reviewer/reviewee and public flag
    if user.role == UserRole.BUYER and booking.buyer_id == user.id:
        if not booking.mechanic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot review: no mechanic assigned to this booking",
            )
        reviewee_id = booking.mechanic.user_id
        is_public = True
    elif user.role == UserRole.MECHANIC:
        mech_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = mech_result.scalar_one_or_none()
        if not profile or booking.mechanic_id != profile.id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this booking")
        reviewee_id = booking.buyer_id
        is_public = False
    else:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not a participant of this booking")

    review = Review(
        booking_id=booking.id,
        reviewer_id=user.id,
        reviewee_id=reviewee_id,
        rating=body.rating,
        comment=body.comment,
        is_public=is_public,
    )
    db.add(review)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Already reviewed this booking")

    # BUG-002: Update mechanic rating atomically using a single UPDATE with
    # subquery to avoid race conditions when concurrent reviews are created.
    if is_public:
        avg_subq = (
            select(func.round(func.avg(Review.rating), 2))
            .where(Review.reviewee_id == reviewee_id, Review.is_public == True)
            .correlate_except(Review)
            .scalar_subquery()
        )
        count_subq = (
            select(func.count(Review.id))
            .where(Review.reviewee_id == reviewee_id, Review.is_public == True)
            .correlate_except(Review)
            .scalar_subquery()
        )
        await db.execute(
            update(MechanicProfile)
            .where(MechanicProfile.user_id == reviewee_id)
            .values(rating_avg=avg_subq, total_reviews=count_subq)
        )
        await db.flush()

    logger.info("review_created", review_id=str(review.id), booking_id=str(booking.id))
    return ReviewResponse.model_validate(review)


@router.get("", response_model=list[ReviewResponse])
@limiter.limit(LIST_RATE_LIMIT)
async def list_reviews(
    request: Request,
    mechanic_id: uuid.UUID = Query(...),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0, le=10000),
    db: AsyncSession = Depends(get_db),
):
    """List public reviews for a mechanic.

    Uses a single JOIN query instead of two separate queries (one to look up
    the mechanic profile, then another to fetch reviews) for better performance.
    """
    # BUG-014: Always verify mechanic exists before fetching reviews
    profile_result = await db.execute(
        select(MechanicProfile.id).where(MechanicProfile.id == mechanic_id)
    )
    if not profile_result.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Mechanic not found")

    result = await db.execute(
        select(Review)
        .join(MechanicProfile, MechanicProfile.user_id == Review.reviewee_id)
        .where(MechanicProfile.id == mechanic_id, Review.is_public == True)  # noqa: E712
        .order_by(Review.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    reviews = result.scalars().all()

    return [ReviewResponse.model_validate(r) for r in reviews]
