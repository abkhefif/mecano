import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ReviewCreateRequest(BaseModel):
    booking_id: uuid.UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(None, max_length=500)


class ReviewResponse(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    reviewer_id: uuid.UUID
    reviewee_id: uuid.UUID
    rating: int
    comment: str | None
    is_public: bool
    created_at: datetime

    model_config = {"from_attributes": True}
