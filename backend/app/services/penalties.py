from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.mechanic_profile import MechanicProfile

logger = structlog.get_logger()


async def apply_no_show_penalty(
    db: AsyncSession, mechanic: MechanicProfile
) -> None:
    """Apply progressive penalty to a mechanic for a no-show."""
    mechanic.no_show_count += 1
    mechanic.last_no_show_at = datetime.now(timezone.utc)

    if mechanic.no_show_count >= 3:
        mechanic.is_active = False
        logger.warning(
            "mechanic_banned",
            mechanic_id=str(mechanic.id),
            no_show_count=mechanic.no_show_count,
        )
    elif mechanic.no_show_count >= 2:
        mechanic.suspended_until = datetime.now(timezone.utc) + timedelta(days=30)
        logger.warning(
            "mechanic_suspended",
            mechanic_id=str(mechanic.id),
            suspended_until=mechanic.suspended_until.isoformat(),
        )
    else:
        logger.info(
            "mechanic_no_show_warning",
            mechanic_id=str(mechanic.id),
            no_show_count=mechanic.no_show_count,
        )

    await db.flush()


async def reset_no_show_if_eligible(
    db: AsyncSession, mechanic: MechanicProfile
) -> None:
    """Reset no-show counter if 3 months have passed since last incident."""
    if mechanic.last_no_show_at is None:
        return

    three_months_ago = datetime.now(timezone.utc) - timedelta(days=90)
    if mechanic.last_no_show_at < three_months_ago and mechanic.no_show_count > 0:
        mechanic.no_show_count = 0
        mechanic.last_no_show_at = None
        logger.info(
            "mechanic_no_show_reset",
            mechanic_id=str(mechanic.id),
        )
        await db.flush()
