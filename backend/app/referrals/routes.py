import secrets
import string

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies import get_current_mechanic
from app.models.mechanic_profile import MechanicProfile
from app.models.referral import ReferralCode
from app.models.user import User
from app.schemas.referral import ReferralCodeResponse
from app.utils.rate_limit import AUTH_RATE_LIMIT, limiter

logger = structlog.get_logger()
router = APIRouter()

# Maximum attempts to generate a unique referral code before giving up (ARCH-006)
MAX_REFERRAL_CODE_GENERATION_ATTEMPTS = 10


def _generate_referral_code() -> str:
    """Generate a referral code in format EMECANO-XXXXXX."""
    chars = string.ascii_uppercase + string.digits
    suffix = "".join(secrets.choice(chars) for _ in range(6))
    return f"EMECANO-{suffix}"


@router.post("/generate", response_model=ReferralCodeResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/hour")
async def generate_referral_code(
    request: Request,
    mechanic_data: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Generate a referral code for the current mechanic. Returns existing code if one already exists."""
    user, profile = mechanic_data

    # Check if mechanic already has a code
    result = await db.execute(
        select(ReferralCode).where(ReferralCode.mechanic_id == profile.id)
    )
    existing = result.scalar_one_or_none()
    if existing:
        return ReferralCodeResponse.model_validate(existing)

    # Generate a unique code
    for _ in range(MAX_REFERRAL_CODE_GENERATION_ATTEMPTS):
        code = _generate_referral_code()
        check = await db.execute(
            select(ReferralCode).where(ReferralCode.code == code)
        )
        if check.scalar_one_or_none() is None:
            break
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate unique referral code",
        )

    referral = ReferralCode(
        code=code,
        mechanic_id=profile.id,
        uses_count=0,
    )
    db.add(referral)
    await db.flush()

    logger.info("referral_code_generated", mechanic_id=str(profile.id), code=code)
    return ReferralCodeResponse.model_validate(referral)


@router.get("/my-code", response_model=ReferralCodeResponse)
async def get_my_referral_code(
    mechanic_data: tuple[User, MechanicProfile] = Depends(get_current_mechanic),
    db: AsyncSession = Depends(get_db),
):
    """Get the current mechanic's referral code and stats."""
    user, profile = mechanic_data

    result = await db.execute(
        select(ReferralCode).where(ReferralCode.mechanic_id == profile.id)
    )
    referral = result.scalar_one_or_none()
    if not referral:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No referral code found. Generate one first.",
        )

    return ReferralCodeResponse.model_validate(referral)


@router.get("/validate/{code}")
@limiter.limit(AUTH_RATE_LIMIT)
async def validate_referral_code(
    request: Request,
    code: str,
    db: AsyncSession = Depends(get_db),
):
    """Check if a referral code is valid (public endpoint for registration).

    SEC-018: Returns a generic {"valid": true/false} without distinguishing
    between "code does not exist" and "code is invalid/expired" to prevent
    referral code enumeration.
    """
    result = await db.execute(
        select(ReferralCode).where(ReferralCode.code == code)
    )
    referral = result.scalar_one_or_none()
    # SEC-018: Uniform response — do not leak whether the code exists
    return {"valid": referral is not None}
