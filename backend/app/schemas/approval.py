import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ApprovalBase(BaseModel):
    content_id: uuid.UUID
    calendar_item_id: uuid.UUID
    reviewer_id: uuid.UUID


class ApprovalCreate(ApprovalBase):
    pass


class ApprovalDecision(BaseModel):
    status: str  # "approved", "rejected", "revision_requested"
    feedback: str | None = None


class ApprovalResponse(ApprovalBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    feedback: str | None = None
    decided_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
