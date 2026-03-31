import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict


class ProductBase(BaseModel):
    brand_id: uuid.UUID
    name: str
    bc_item_no: str | None = None
    bc_item_category: str | None = None
    description: str | None = None
    short_description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    unit_price: float | None = None
    currency: str | None = None
    category: str | None = None
    subcategory: str | None = None
    attributes: dict | None = None
    tags: list[str] | None = None
    image_urls: dict | list | None = None
    primary_image_url: str | None = None
    vendor_name: str | None = None
    vendor_no: str | None = None
    bc_company: str | None = None
    bc_location: str | None = None
    remaining_qty: float | None = None
    lot_no: str | None = None
    is_active: bool = False
    is_new: bool = False
    is_expiring_soon: bool = False
    expiry_date: date | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    brand_id: uuid.UUID | None = None
    name: str | None = None
    bc_item_no: str | None = None
    bc_item_category: str | None = None
    description: str | None = None
    short_description: str | None = None
    sku: str | None = None
    barcode: str | None = None
    unit_price: float | None = None
    currency: str | None = None
    category: str | None = None
    subcategory: str | None = None
    attributes: dict | None = None
    tags: list[str] | None = None
    image_urls: dict | list | None = None
    primary_image_url: str | None = None
    vendor_name: str | None = None
    vendor_no: str | None = None
    bc_company: str | None = None
    bc_location: str | None = None
    remaining_qty: float | None = None
    lot_no: str | None = None
    is_active: bool | None = None
    is_new: bool | None = None
    is_expiring_soon: bool | None = None
    expiry_date: date | None = None


class ProductResponse(ProductBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    bc_last_synced_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
