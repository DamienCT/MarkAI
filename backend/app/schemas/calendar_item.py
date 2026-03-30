import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class CalendarItemBase(BaseModel):
    brand_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    item_type: str
    channel: str
    scheduled_at: datetime | None = None
    status: str = "queued"
    assigned_to: uuid.UUID | None = None
    pillar: str | None = None
    theme: str | None = None
    target_audience: str | None = None
    weekly_sub_theme: str | None = None
    content_brief: str | None = None
    visual_direction: str | None = None
    cta_type: str | None = None
    product_ids: list[uuid.UUID] | None = None
    tags: list[str] | None = None
    priority: int | None = None


class CalendarItemCreate(CalendarItemBase):
    pass


class CalendarItemUpdate(BaseModel):
    campaign_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    item_type: str | None = None
    channel: str | None = None
    scheduled_at: datetime | None = None
    status: str | None = None
    assigned_to: uuid.UUID | None = None
    pillar: str | None = None
    theme: str | None = None
    target_audience: str | None = None
    weekly_sub_theme: str | None = None
    content_brief: str | None = None
    visual_direction: str | None = None
    cta_type: str | None = None
    product_ids: list[uuid.UUID] | None = None
    tags: list[str] | None = None
    priority: int | None = None


class CalendarItemResponse(CalendarItemBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    brand_name: str | None = None
    published_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
