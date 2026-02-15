import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=500)
    is_template: bool = True


class MessageResponse(BaseModel):
    id: uuid.UUID
    booking_id: uuid.UUID
    sender_id: uuid.UUID
    is_template: bool
    content: str
    created_at: datetime
    sender_name: str | None = None

    model_config = {"from_attributes": True}


class TemplateMessage(BaseModel):
    category: str
    messages: list[str]
