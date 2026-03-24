import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class CampaignBase(BaseModel):
    brand_id: uuid.UUID
    name: str
    description: str | None = None
    objective: str | None = None
    status: str = "draft"
    start_date: date | None = None
    end_date: date | None = None
    budget: dict | None = None
    target_channels: list[str] | None = None
    target_audience: dict | None = None
    kpis: dict | None = None


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    objective: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget: dict | None = None
    target_channels: list[str] | None = None
    target_audience: dict | None = None
    kpis: dict | None = None


class CampaignResponse(CampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
