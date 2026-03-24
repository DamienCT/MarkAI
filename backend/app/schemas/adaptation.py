import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AdaptationBase(BaseModel):
    source_content_id: uuid.UUID
    target_channel: str
    adapted_text: str | None = None
    adapted_headline: str | None = None
    adapted_hashtags: list[str] | None = None
    adapted_media: dict | None = None
    adaptation_notes: str | None = None
    ai_model: str | None = None
    status: str = "queued"
    created_by: uuid.UUID | None = None


class AdaptationCreate(AdaptationBase):
    pass


class AdaptationUpdate(BaseModel):
    target_channel: str | None = None
    adapted_text: str | None = None
    adapted_headline: str | None = None
    adapted_hashtags: list[str] | None = None
    adapted_media: dict | None = None
    adaptation_notes: str | None = None
    ai_model: str | None = None
    status: str | None = None


class AdaptationResponse(AdaptationBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime
