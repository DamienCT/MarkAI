import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class VideoJob(Base):
    """A provider-agnostic video render job (local Video Forge or cloud).

    One row per render attempt lifecycle: queued → submitted → running →
    succeeded/failed/cancelled. The worker owns status transitions; the
    backend only inserts/reads rows and publishes render requests to NATS.
    """

    __tablename__ = "video_jobs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    calendar_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("calendar_items.id", ondelete="CASCADE"),
        nullable=True,
    )
    content_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content.id", ondelete="SET NULL"), nullable=True
    )
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    # 'i2v' | 't2v' | 'flf2v' | 'extend' (DB CHECK)
    mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="i2v", server_default="i2v"
    )
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    source_image_object: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    params: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    # 'queued' | 'submitted' | 'running' | 'succeeded' | 'failed' | 'cancelled' (DB CHECK)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="queued", server_default="queued"
    )
    progress: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    attempt: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    provider_job_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    output_object: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    thumbnail_object: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    duration_s: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 4), nullable=True, default=0, server_default="0"
    )
    generation_ledger: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
