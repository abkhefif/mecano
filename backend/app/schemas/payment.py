import uuid
from typing import Literal

from pydantic import BaseModel, Field


class OnboardResponse(BaseModel):
    onboarding_url: str


class DashboardLinkResponse(BaseModel):
    dashboard_url: str


class DisputeResolveRequest(BaseModel):
    dispute_id: uuid.UUID
    resolution: Literal["buyer", "mechanic"]
    resolution_notes: str = Field(default="", max_length=2000)
