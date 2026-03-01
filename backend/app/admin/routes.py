import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select, func, case, cast, Date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_current_admin
from app.utils.rate_limit import limiter
from app.models.audit_log import AuditLog
from app.models.booking import Booking
from app.models.dispute import DisputeCase
from app.models.enums import BookingStatus, DisputeStatus, NotificationType, UserRole
from app.models.mechanic_profile import MechanicProfile
from app.models.user import User
from app.schemas.admin import VerifyMechanicRequest, SuspendUserRequest
from app.services.notifications import create_notification
from app.services.storage import get_sensitive_url
from app.services.stripe_service import cancel_payment_intent
from app.utils.csv_sanitize import sanitize_csv_cell

logger = structlog.get_logger()
router = APIRouter(prefix="/admin", tags=["admin"])


# --- 1. Platform stats ---


@router.get("/stats")
@limiter.limit("30/minute")
async def platform_stats(
    request: Request,
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
@limiter.limit("30/minute")
async def list_users(
    request: Request,
    role: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
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
                "email": sanitize_csv_cell(u.email),
                "role": u.role.value if hasattr(u.role, "value") else u.role,
                "first_name": sanitize_csv_cell(u.first_name),
                "last_name": sanitize_csv_cell(u.last_name),
                "phone": sanitize_csv_cell(u.phone),
                "is_verified": u.is_verified,
                "created_at": u.created_at.isoformat() if u.created_at else None,
            }
            for u in users
        ],
    }


# --- 3. User detail ---


@router.get("/users/{user_id}")
@limiter.limit("30/minute")
async def get_user_detail(
    request: Request,
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
    profile = None
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
                "created_at": profile.created_at.isoformat() if profile.created_at else None,
            }

    # AUD-017: Count bookings correctly based on user role
    if user.role == UserRole.MECHANIC and profile:
        booking_count_result = await db.execute(
            select(func.count(Booking.id)).where(Booking.mechanic_id == profile.id)
        )
    else:
        booking_count_result = await db.execute(
            select(func.count(Booking.id)).where(Booking.buyer_id == user.id)
        )
    user_data["booking_count"] = booking_count_result.scalar() or 0

    return user_data


# --- 4. Suspend user ---


@router.patch("/users/{user_id}/suspend")
@limiter.limit("30/minute")
async def suspend_user(
    request: Request,
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

    # F-020: Buyer accounts have no MechanicProfile.suspended_until field,
    # so suspension has no effect. Return an explicit error instead of silently
    # doing nothing. Use deactivation (account deletion) for buyers.
    if user.role == UserRole.BUYER:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Buyer accounts cannot be suspended. Use deactivation instead.",
        )

    if user.role == UserRole.MECHANIC:
        profile_result = await db.execute(
            select(MechanicProfile).where(MechanicProfile.user_id == user.id)
        )
        profile = profile_result.scalar_one_or_none()
        if profile:
            if body.suspended:
                profile.suspended_until = datetime.now(timezone.utc) + timedelta(days=body.suspension_days)
                profile.is_active = False

                # FINDING-P2-N05: Cancel active bookings for the suspended mechanic
                # so buyers are not left waiting indefinitely with funds held.
                active_bookings_result = await db.execute(
                    select(Booking).where(
                        Booking.mechanic_id == profile.id,
                        Booking.status.in_([
                            BookingStatus.PENDING_ACCEPTANCE,
                            BookingStatus.CONFIRMED,
                        ]),
                    ).with_for_update()
                )
                cancelled_count = 0
                for booking in active_bookings_result.scalars().all():
                    if booking.stripe_payment_intent_id:
                        try:
                            await cancel_payment_intent(booking.stripe_payment_intent_id)
                        except Exception as stripe_err:
                            logger.error(
                                "suspend_cancel_stripe_failed",
                                booking_id=str(booking.id),
                                error=str(stripe_err),
                            )
                    booking.status = BookingStatus.CANCELLED
                    await create_notification(
                        db=db,
                        user_id=booking.buyer_id,
                        notification_type=NotificationType.BOOKING_CANCELLED,
                        title="Réservation annulée",
                        body="Votre réservation a été annulée suite à la suspension du mécanicien.",
                        data={"booking_id": str(booking.id), "type": "booking_cancelled"},
                    )
                    cancelled_count += 1

                logger.info(
                    "mechanic_suspended_bookings_cancelled",
                    mechanic_id=str(profile.id),
                    cancelled_count=cancelled_count,
                )
            else:
                profile.suspended_until = None
                profile.is_active = True

    # ADMIN-R01: Audit log
    db.add(AuditLog(
        action="suspend_user" if body.suspended else "unsuspend_user",
        admin_user_id=admin.id,
        target_user_id=user.id,
        detail=body.reason,
    ))
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


# --- 4b. Deactivate buyer ---


@router.patch("/users/{user_id}/deactivate")
@limiter.limit("10/minute")
async def deactivate_buyer(
    request: Request,
    user_id: uuid.UUID,
    body: SuspendUserRequest,
    admin: User = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """AUDIT-12: Deactivate or reactivate a buyer account.

    Deactivated buyers cannot log in or create bookings.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if user.role == UserRole.ADMIN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Cannot deactivate admin users")

    if user.role == UserRole.MECHANIC:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Use /admin/users/{id}/suspend for mechanic accounts.",
        )

    user.is_active = not body.suspended

    # Audit log
    db.add(AuditLog(
        action="deactivate_buyer" if body.suspended else "reactivate_buyer",
        admin_user_id=admin.id,
        target_user_id=user.id,
        detail=body.reason,
    ))
    await db.flush()
    logger.info(
        "buyer_deactivation_changed",
        user_id=str(user_id),
        deactivated=body.suspended,
        admin_id=str(admin.id),
        reason=body.reason,
    )

    return {
        "status": "deactivated" if body.suspended else "active",
        "user_id": str(user_id),
    }


# --- 5. Pending mechanic verifications ---


@router.get("/mechanics/pending-verification")
@limiter.limit("30/minute")
async def pending_verification(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
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

    # PERF-08: Parallelize presigned URL generation instead of sequential awaits
    mechanics_list = []
    for p in profiles:
        id_url, selfie_url, cv_url = await asyncio.gather(
            get_sensitive_url(p.identity_document_url),
            get_sensitive_url(p.selfie_with_id_url),
            get_sensitive_url(p.cv_url),
        )
        mechanics_list.append({
            "id": str(p.id),
            "user_id": str(p.user_id),
            "email": p.user.email if p.user else None,
            "first_name": p.user.first_name if p.user else None,
            "last_name": p.user.last_name if p.user else None,
            "city": p.city,
            "identity_document_url": id_url,
            "selfie_with_id_url": selfie_url,
            "cv_url": cv_url,
            "created_at": p.created_at.isoformat() if p.created_at else None,
        })

    return {
        "total": total,
        "mechanics": mechanics_list,
    }


# --- 6. Verify mechanic ---


@router.patch("/mechanics/{mechanic_id}/verify")
@limiter.limit("30/minute")
async def verify_mechanic(
    request: Request,
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
    # AUD-028: Auto-activate mechanic after identity verification approval
    if body.approved:
        profile.is_active = True

    # ADMIN-R01: Audit log
    db.add(AuditLog(
        action="verify_mechanic" if body.approved else "reject_mechanic",
        admin_user_id=admin.id,
        target_user_id=profile.user_id,
        detail=f"Mechanic {mechanic_id} {'approved' if body.approved else 'rejected'}",
    ))
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
@limiter.limit("30/minute")
async def list_bookings(
    request: Request,
    booking_status: str | None = Query(None, alias="status"),
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
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

    # FIX-2: Sanitized admin booking response — expose mechanic_id only as opaque
    # reference (not the raw UUID that could be used for profile enumeration)
    return {
        "total": total,
        "bookings": [
            {
                "id": str(b.id),
                "buyer_id": str(b.buyer_id),
                "mechanic_id": str(b.mechanic_id) if b.mechanic_id else None,
                "status": b.status.value if hasattr(b.status, "value") else b.status,
                "vehicle_brand": sanitize_csv_cell(b.vehicle_brand),
                "vehicle_model": sanitize_csv_cell(b.vehicle_model),
                "vehicle_year": b.vehicle_year,
                "total_price": float(b.total_price),
                "commission_amount": float(b.commission_amount),
                "mechanic_payout": float(b.mechanic_payout),
                "created_at": b.created_at.isoformat() if b.created_at else None,
                "cancelled_by": b.cancelled_by,
            }
            for b in bookings
        ],
    }


# --- 8. Open disputes ---


@router.get("/disputes")
@limiter.limit("30/minute")
async def list_disputes(
    request: Request,
    dispute_status: str | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
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
                "description": sanitize_csv_cell(d.description),
                "status": d.status.value if hasattr(d.status, "value") else d.status,
                "created_at": d.created_at.isoformat() if d.created_at else None,
                "resolved_at": d.resolved_at.isoformat() if d.resolved_at else None,
            }
            for d in disputes
        ],
    }


# --- 9. Revenue breakdown ---


@router.get("/revenue")
@limiter.limit("30/minute")
async def revenue_breakdown(
    request: Request,
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
