import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


ALL_CHANNELS = [
    "instagram",
    "facebook",
    "linkedin",
    "youtube",
    "tiktok",
    "x",
    "website_blog",
    "teams",
]

CHANNEL_DISPLAY_NAMES = {
    "instagram": "Instagram",
    "facebook": "Facebook",
    "linkedin": "LinkedIn",
    "youtube": "YouTube",
    "tiktok": "TikTok",
    "x": "X (Twitter)",
    "website_blog": "Website / Blog",
    "teams": "Teams",
}

# Expected structure for brand_guidelines["channels"]:
# {
#   "channels": {
#     "instagram": {"enabled": true, "configured": true, "handle": "@brand", "access_token": "..."},
#     "facebook": {"enabled": true, "configured": true, "page_id": "...", "access_token": "..."},
#     "linkedin": {"enabled": true, "configured": false},
#     "youtube": {"enabled": false},
#     "tiktok": {"enabled": false},
#     "x": {"enabled": false},
#     "website_blog": {"enabled": true, "configured": true, "url": "https://blog.example.com"},
#     "teams": {"enabled": false}
#   }
# }


class Brand(Base):
    __tablename__ = "brands"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_guidelines: Mapped[dict] = mapped_column(JSONB, default=dict)
    tone_of_voice: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[dict] = mapped_column(JSONB, default=dict)
    color_palette: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="onboarding"
    )
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    activation_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_bc_linked: Mapped[bool] = mapped_column(Boolean, default=False)
    bc_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bc_locations: Mapped[list] = mapped_column(JSONB, default=list)
    # Filters applied to BC sync (manual + scheduled). Empty list = no filter.
    bc_sync_vendor_nos: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    bc_sync_categories: Mapped[list] = mapped_column(JSONB, default=list, server_default="[]")
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    products = relationship("Product", back_populates="brand")
    campaigns = relationship("Campaign", back_populates="brand")
    calendar_items = relationship("CalendarItem", back_populates="brand")
    competitors = relationship("Competitor", back_populates="brand")
    agent_runs = relationship("AgentRun", back_populates="brand")
    content_items = relationship("Content", back_populates="brand", foreign_keys="[Content.brand_id]")
    engagement_metrics = relationship("EngagementMetric", back_populates="brand", foreign_keys="[EngagementMetric.brand_id]")
