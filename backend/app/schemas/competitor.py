import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CompetitorBase(BaseModel):
    brand_id: uuid.UUID
    name: str
    website_url: str | None = None
    social_handles: dict | None = None
    description: str | None = None
    monitoring_config: dict | None = None
    is_active: bool = True
    created_by: uuid.UUID | None = None


class CompetitorCreate(CompetitorBase):
    pass


class CompetitorUpdate(BaseModel):
    name: str | None = None
    website_url: str | None = None
    social_handles: dict | None = None
    description: str | None = None
    monitoring_config: dict | None = None
    is_active: bool | None = None


class CompetitorResponse(CompetitorBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
