import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ContentBase(BaseModel):
    calendar_item_id: uuid.UUID
    brand_id: uuid.UUID
    version: int = 1
    body_text: str | None = None
    headline: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    cta_text: str | None = None
    cta_url: str | None = None
    image_urls: dict | None = None
    video_url: str | None = None
    media_assets: dict | None = None
    platform_metadata: dict | None = None
    ai_generated: bool = False
    ai_model: str | None = None
    ai_prompt_version: uuid.UUID | None = None
    generation_metadata: dict | None = None
    is_current: bool = True


class ContentCreate(ContentBase):
    pass


class ContentUpdate(BaseModel):
    calendar_item_id: uuid.UUID | None = None
    version: int | None = None
    body_text: str | None = None
    headline: str | None = None
    caption: str | None = None
    hashtags: list[str] | None = None
    cta_text: str | None = None
    cta_url: str | None = None
    image_urls: dict | None = None
    video_url: str | None = None
    media_assets: dict | None = None
    platform_metadata: dict | None = None
    ai_generated: bool | None = None
    ai_model: str | None = None
    ai_prompt_version: uuid.UUID | None = None
    generation_metadata: dict | None = None
    is_current: bool | None = None


class ContentResponse(ContentBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    platform_post_id: str | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
