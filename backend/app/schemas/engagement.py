import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.calendar_item import ChannelType


class EngagementMetricBase(BaseModel):
    content_id: uuid.UUID
    calendar_item_id: uuid.UUID
    brand_id: uuid.UUID
    channel: ChannelType
    impressions: int | None = None
    reach: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    clicks: int | None = None
    video_views: int | None = None
    engagement_rate: Decimal | None = None
    sentiment_score: Decimal | None = None
    raw_metrics: dict | None = None


class EngagementMetricCreate(EngagementMetricBase):
    fetched_at: datetime


class EngagementMetricResponse(EngagementMetricBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    fetched_at: datetime
    created_at: datetime


class EngagementAggregation(BaseModel):
    """Aggregated engagement metrics for analytics endpoints."""

    total_impressions: int = 0
    total_reach: int = 0
    total_likes: int = 0
    total_comments: int = 0
    total_shares: int = 0
    total_saves: int = 0
    total_clicks: int = 0
    total_video_views: int = 0
    avg_engagement_rate: float | None = None
    content_count: int = 0
