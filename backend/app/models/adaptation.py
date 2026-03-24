import uuid
from datetime import datetime

from sqlalchemy import ARRAY, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Adaptation(Base):
    __tablename__ = "adaptations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source_content_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content.id"), nullable=False
    )
    target_channel: Mapped[str] = mapped_column(String(255), nullable=False)
    adapted_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    adapted_headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    adapted_hashtags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    adapted_media: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    adaptation_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="queued")
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
    source_content = relationship("Content", back_populates="adaptations")
