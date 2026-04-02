import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class Product(Base):
    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    brand_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("brands.id", ondelete="CASCADE"), nullable=False
    )
    bc_item_no: Mapped[str | None] = mapped_column(String(50), nullable=True)
    bc_item_category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    short_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sku: Mapped[str | None] = mapped_column(String(255), nullable=True)
    barcode: Mapped[str | None] = mapped_column(String(255), nullable=True)
    unit_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(255), nullable=True, default="MUR")
    category: Mapped[str | None] = mapped_column(String(255), nullable=True)
    subcategory: Mapped[str | None] = mapped_column(String(255), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    tags: Mapped[list | None] = mapped_column(ARRAY(String), nullable=True)
    image_urls: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    primary_image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    vendor_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    vendor_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bc_company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    bc_location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    remaining_qty: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    lot_no: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_new: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_expiring_soon: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    expiry_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bc_last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # Relationships
    brand = relationship("Brand", back_populates="products")
