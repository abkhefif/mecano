from pydantic import BaseModel, Field


class VerifyMechanicRequest(BaseModel):
    approved: bool


class SuspendUserRequest(BaseModel):
    suspended: bool
    reason: str | None = Field(None, max_length=500)
