import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select, func, case, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_admin
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import BookingStatus, DisputeStatus, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


# --- Request / Response schemas ---


class VerifyMechanicRequest(BaseModel):
    approved: bool


class SuspendUserRequest(BaseModel):
    suspended: bool
    reason: str | None = None


# --- 1. Platform stats ---


@router.get("/stats")
async def platform_stats(
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return high-level platform statistics."""
    # Count users by role
    role_counts_result = await db.execute(
        select(User.role, func.count(User.id)).group_by(User.role)
    )
    role_counts = {row[0]: row[1] for row in role_counts_result}

    # Total bookings
    total_bookings_result = await db.execute(select(func.count(Booking.id)))
    total_bookings = total_bookings_result.scalar() or 0

    # Total revenue and commission (completed bookings)
    revenue_result = await db.execute(
        select(
            func.coalesce(func.sum(Booking.total_price), 0),
            func.coalesce(func.sum(Booking.commission_amount), 0),
        ).where(Booking.status == BookingStatus.COMPLETED)
    )
    total_revenue, total_commission = revenue_result.one()

    # This month stats
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    month_result = await db.execute(
        select(
            func.count(Booking.id),
            func.coalesce(func.sum(Booking.total_price), 0),
            func.coalesce(func.sum(Booking.commission_amount), 0),
        ).where(
            Booking.status == BookingStatus.COMPLETED,
            Booking.created_at >= month_start,
        )
    )
    month_bookings, month_revenue, month_commission = month_result.one()

    # Open disputes
    open_disputes_result = await db.execute(
        select(func.count(DisputeCase.id)).where(DisputeCase.status == DisputeStatus.OPEN)
    )
    open_disputes = open_disputes_result.scalar() or 0

    return {
        "users": {
            "buyers": role_counts.get(UserRole.BUYER, 0),
            "mechanics": role_counts.get(UserRole.MECHANIC, 0),
            "admins": role_counts.get(UserRole.ADMIN, 0),
            "total": sum(role_counts.values()),
        },
        "bookings": {
            "total": total_bookings,
            "this_month": month_bookings,
        },
        "revenue": {
            "total": float(total_revenue),
            "total_commission": float(total_commission),
            "this_month": float(month_revenue),
            "this_month_commission": float(month_commission),
        },
        "open_disputes": open_disputes,
    }


# --- 2. List users ---


@router.get("/users")
async def list_users(
    role: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List users with optional role filter and pagination."""
    stmt = select(User)
    count_stmt = select(func.count(User.id))

    if role:
        try:
            role_enum = UserRole(role)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid role: {role}. Must be one of: buyer, mechanic, admin",
            )
        stmt = stmt.where(User.role == role_enum)
        count_stmt = count_stmt.where(User.role == role_enum)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(User.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    users = result.scalars().all()

    return {
        "total": total,
        "users": [
            {
                "id": str(u.id),
                "email": u.email,
                "role": u.role.value if hasattr(u.role, "value") else u.role,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "phone": u.phone,
                "is_verified": u.is_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
    }


# --- 3. User detail ---


@router.get("/users/{user_id}")
async def get_user_detail(
    user_id: uuid.UUID,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get detailed user information."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user_data = {
        "id": str(user.id),
        "email": user.email,
        "role": user.role.value if hasattr(user.role, "value") else user.role,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "phone": user.phone,
        "is_verified": user.is_verified,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "updated_at": user.updated_at.isoformat() if user.updated_at else None,
    }

    # If mechanic, include profile info
    if user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            user_data["mechanic_profile"] = {
                "id": str(profile.id),
                "city": profile.city,
                "is_identity_verified": profile.is_identity_verified,
                "is_active": profile.is_active,
                "rating_avg": float(profile.rating_avg),
                "total_reviews": profile.total_reviews,
                "has_obd_diagnostic": profile.has_obd_diagnostic,
                "no_show_count": profile.no_show_count,
                "suspended_until": profile.suspended_until.isoformat() if profile.suspended_until else None,
                "stripe_account_id": profile.stripe_account_id,
                "created_at": profile.created_at.isoformat() if profile.created_at else None,
            }

    # Booking count
    booking_count_result = await db.execute(
        select(func.count(Booking.id)).where(Booking.buyer_id == user.id)
    )
    user_data["booking_count"] = booking_count_result.scalar() or 0

    return user_data


# --- 4. Suspend user ---


@router.patch("/users/{user_id}/suspend")
async def suspend_user(
    user_id: uuid.UUID,
    body: SuspendUserRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Suspend or unsuspend a user. For mechanics, sets suspended_until."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if user.role == UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot suspend admin users",
        )

    if user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            if body.suspended:
                # Suspend for 30 days by default
                profile.suspended_until = datetime.now(timezone.utc) + timedelta(days=30)
                profile.is_active = False
            else:
                profile.suspended_until = None
                profile.is_active = True

    await db.flush()
    logger.info(
        "user_suspension_changed",
        user_id=str(user_id),
        suspended=body.suspended,
        admin_id=str(admin.id),
        reason=body.reason,
    )

    return {
        "status": "suspended" if body.suspended else "active",
        "user_id": str(user_id),
    }


# --- 5. Pending mechanic verifications ---


@router.get("/mechanics/pending-verification")
async def pending_verification(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List mechanic profiles that have uploaded identity documents but are not yet verified."""
    stmt = (
        select(MechanicProfile)
        .options(selectinload(MechanicProfile.user))
        .where(
            MechanicProfile.identity_document_url.isnot(None),
            MechanicProfile.is_identity_verified == False,
        )
        .order_by(MechanicProfile.created_at.asc())
        .offset(offset)
        .limit(limit)
    )
    result = await db.execute(stmt)
    profiles = result.scalars().all()

    count_stmt = select(func.count(MechanicProfile.id)).where(
        MechanicProfile.identity_document_url.isnot(None),
        MechanicProfile.is_identity_verified == False,
    )
    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    return {
        "total": total,
        "mechanics": [
            {
                "id": str(p.id),
                "user_id": str(p.user_id),
                "email": p.user.email if p.user else None,
                "first_name": p.user.first_name if p.user else None,
                "last_name": p.user.last_name if p.user else None,
                "city": p.city,
                "identity_document_url": p.identity_document_url,
                "selfie_with_id_url": p.selfie_with_id_url,
                "cv_url": p.cv_url,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in profiles
        ],
    }


# --- 6. Verify mechanic ---


@router.patch("/mechanics/{mechanic_id}/verify")
async def verify_mechanic(
    mechanic_id: uuid.UUID,
    body: VerifyMechanicRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a mechanic's identity verification."""
    result = await db.execute(
        select(MechanicProfile).where(MechanicProfile.id == mechanic_id)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mechanic profile not found",
        )

    profile.is_identity_verified = body.approved
    await db.flush()

    logger.info(
        "mechanic_verification_changed",
        mechanic_id=str(mechanic_id),
        approved=body.approved,
        admin_id=str(admin.id),
    )

    return {
        "mechanic_id": str(mechanic_id),
        "is_identity_verified": profile.is_identity_verified,
    }


# --- 7. List bookings ---


@router.get("/bookings")
async def list_bookings(
    booking_status: str | None = Query(None, alias="status"),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all bookings with optional filters."""
    stmt = select(Booking)
    count_stmt = select(func.count(Booking.id))

    if booking_status:
        try:
            status_enum = BookingStatus(booking_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {booking_status}",
            )
        stmt = stmt.where(Booking.status == status_enum)
        count_stmt = count_stmt.where(Booking.status == status_enum)

    if date_from:
        try:
            dt_from = datetime.fromisoformat(date_from).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date_from format. Use ISO 8601 (e.g. 2025-01-01)",
            )
        stmt = stmt.where(Booking.created_at >= dt_from)
        count_stmt = count_stmt.where(Booking.created_at >= dt_from)

    if date_to:
        try:
            dt_to = datetime.fromisoformat(date_to).replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid date_to format. Use ISO 8601 (e.g. 2025-01-31)",
            )
        stmt = stmt.where(Booking.created_at <= dt_to)
        count_stmt = count_stmt.where(Booking.created_at <= dt_to)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(Booking.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    bookings = result.scalars().all()

    return {
        "total": total,
        "bookings": [
            {
                "id": str(b.id),
                "buyer_id": str(b.buyer_id),
                "mechanic_id": str(b.mechanic_id),
                "status": b.status.value if hasattr(b.status, "value") else b.status,
                "vehicle_brand": b.vehicle_brand,
                "vehicle_model": b.vehicle_model,
                "vehicle_year": b.vehicle_year,
                "total_price": float(b.total_price),
                "commission_amount": float(b.commission_amount),
                "mechanic_payout": float(b.mechanic_payout),
                "meeting_address": b.meeting_address,
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "cancelled_by": b.cancelled_by,
            }
            for b in bookings
        ],
    }


# --- 8. Open disputes ---


@router.get("/disputes")
async def list_disputes(
    dispute_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """List disputes, optionally filtered by status."""
    stmt = select(DisputeCase).options(selectinload(DisputeCase.opener))
    count_stmt = select(func.count(DisputeCase.id))

    if dispute_status:
        try:
            status_enum = DisputeStatus(dispute_status)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid status: {dispute_status}",
            )
        stmt = stmt.where(DisputeCase.status == status_enum)
        count_stmt = count_stmt.where(DisputeCase.status == status_enum)
    else:
        # Default: show open disputes
        stmt = stmt.where(DisputeCase.status == DisputeStatus.OPEN)
        count_stmt = count_stmt.where(DisputeCase.status == DisputeStatus.OPEN)

    total_result = await db.execute(count_stmt)
    total = total_result.scalar() or 0

    stmt = stmt.order_by(DisputeCase.created_at.asc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    disputes = result.scalars().all()

    return {
        "total": total,
        "disputes": [
            {
                "id": str(d.id),
                "booking_id": str(d.booking_id),
                "opened_by": str(d.opened_by),
                "opener_email": d.opener.email if d.opener else None,
                "reason": d.reason.value if hasattr(d.reason, "value") else d.reason,
                "description": d.description,
                "status": d.status.value if hasattr(d.status, "value") else d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            }
            for d in disputes
        ],
    }


# --- 9. Revenue breakdown ---


@router.get("/revenue")
async def revenue_breakdown(
    days: int = Query(30, ge=1, le=365),
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """Return daily revenue breakdown for the last N days."""
    now = datetime.now(timezone.utc)
    start_date = now - timedelta(days=days)

    stmt = (
        select(
            cast(Booking.created_at, Date).label("date"),
            func.coalesce(func.sum(Booking.total_price), 0).label("revenue"),
            func.coalesce(func.sum(Booking.commission_amount), 0).label("commission"),
            func.count(Booking.id).label("count"),
        )
        .where(
            Booking.status == BookingStatus.COMPLETED,
            Booking.created_at >= start_date,
        )
        .group_by(cast(Booking.created_at, Date))
        .order_by(cast(Booking.created_at, Date))
    )

    result = await db.execute(stmt)
    rows = result.all()

    return {
        "period_days": days,
        "daily": [
            {
                "date": row.date.isoformat() if row.date else None,
                "revenue": float(row.revenue),
                "commission": float(row.commission),
                "count": row.count,
            }
            for row in rows
        ],
    }
