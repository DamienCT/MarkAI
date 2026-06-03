import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class TrendingTopic(Base):
    """A trend (currently from Google Trends) judged by an LLM to be a
    useful marketing angle for a specific brand.

    One row per (brand_id, topic). The same raw trend can be saved for
    several brands when the LLM finds it useful for each independently —
    each row may carry a different `llm_angle` because the pitch is
    tailored to the brand.

    Rows expire after `expires_at` and are cleaned up by the cron.
    """

    __tablename__ = "trending_topics"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("brands.id", ondelete="CASCADE"),
        nullable=False,
    )

    # The trend itself
    topic: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(
        String(50), nullable=False, default="google", server_default="google"
    )
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_metric: Mapped[str | None] = mapped_column(String(50), nullable=True)
    velocity: Mapped[str] = mapped_column(
        String(20), nullable=False, default="stable", server_default="stable"
    )

    # LLM judgement
    relevance_score: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    llm_angle: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Raw payload from the source (for debugging / future filters)
    extra_data: Mapped[dict] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict, server_default="{}"
    )

    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("brand_id", "topic", name="trending_topics_brand_topic_uniq"),
    )
