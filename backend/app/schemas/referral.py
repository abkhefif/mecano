import uuid
from datetime import datetime
from pydantic import BaseModel


class ReferralCodeResponse(BaseModel):
    code: str
    uses_count: int
    created_at: datetime
    model_config = {"from_attributes": True}


class ReferralStatsResponse(BaseModel):
    code: str
    total_referrals: int
    total_earned: float  # Will be calculated later
