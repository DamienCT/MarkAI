import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChannelModelFallback(Base):
    """A model that should be used as a fallback for a specific channel
    when the primary model for the category fails.

    One row per (channel, category) — e.g. ("instagram", "image") points
    to the model the image-generation pipeline should try after the
    globally-active "image" model exhausts its retries. If `is_active`
    is false, this fallback is skipped and the pipeline falls through to
    the ultimate hardcoded safety net (gpt-image-1).
    """

    __tablename__ = "channel_model_fallbacks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    channel: Mapped[str] = mapped_column(String(50), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(255), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("channel", "category", name="channel_model_fallbacks_uniq"),
    )
