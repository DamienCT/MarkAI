import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ChannelType = Literal[
    "instagram",
    "facebook",
    "linkedin",
    "youtube",
    "tiktok",
    "x",
    "website_blog",
    "teams",
]
ItemType = Literal[
    "post", "story", "reel", "carousel", "article", "newsletter", "ad", "event", "other"
]
CalendarItemStatus = Literal[
    "planned",
    "queued",
    "working",
    "rendering",
    "in_review",
    "reworking",
    "approved",
    "scheduled",
    "publishing",
    "published",
    "failed",
]


class CalendarItemBase(BaseModel):
    brand_id: uuid.UUID
    campaign_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    item_type: ItemType
    channel: ChannelType
    scheduled_at: datetime | None = None
    status: CalendarItemStatus = "planned"
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
    generation_metadata: dict | None = None


class CalendarItemCreate(CalendarItemBase):
    pass


class CalendarItemUpdate(BaseModel):
    campaign_id: uuid.UUID | None = None
    title: str | None = None
    description: str | None = None
    item_type: ItemType | None = None
    channel: ChannelType | None = None
    scheduled_at: datetime | None = None
    status: CalendarItemStatus | None = None
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
