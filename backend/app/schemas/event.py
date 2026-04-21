import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class EventBase(BaseModel):
    brand_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    start_date: date
    end_date: date | None = None
    is_annual: bool = True
    category: str | None = None
    source: str = "manual"


class EventCreate(EventBase):
    pass


class EventUpdate(BaseModel):
    brand_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    is_annual: bool | None = None
    category: str | None = None


class EventResponse(EventBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class DetectEventsRequest(BaseModel):
    brand_id: uuid.UUID | None = None
    horizon_months: int = 12
