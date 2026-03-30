import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class CalendarItem(Base):
    __tablename__ = "calendar_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id"), nullable=False
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("campaigns.id"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    item_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    scheduled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
    assigned_to: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    pillar: Mapped[str | None] = mapped_column(String(100), nullable=True)
    theme: Mapped[str | None] = mapped_column(String(255), nullable=True)
    target_audience: Mapped[str | None] = mapped_column(String(255), nullable=True)
    weekly_sub_theme: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_brief: Mapped[str | None] = mapped_column(Text, nullable=True)
    visual_direction: Mapped[str | None] = mapped_column(Text, nullable=True)
    cta_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    product_ids: Mapped[list | None] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=True)
    tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    brand = relationship("Brand", back_populates="calendar_items")
    campaign = relationship("Campaign", back_populates="calendar_items")
    content_items = relationship("Content", back_populates="calendar_item")
    approvals = relationship("Approval", back_populates="calendar_item")
    engagement_metrics = relationship("EngagementMetric", back_populates="calendar_item")
