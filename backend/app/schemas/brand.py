import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

BrandStatus = Literal["onboarding", "activating", "active", "inactive"]


class BrandBase(BaseModel):
    name: str
    slug: str
    description: str | None = None
    website_url: str | None = None
    logo_url: str | None = None
    brand_guidelines: dict = {}
    tone_of_voice: str | None = None
    target_audience: dict = {}
    color_palette: dict = {}
    is_active: bool = False
    status: BrandStatus = "onboarding"
    is_bc_linked: bool = False
    bc_company: str | None = None
    bc_locations: list[str] = []
    bc_sync_vendor_nos: list[str] = []
    bc_sync_categories: list[str] = []


class BrandCreate(BrandBase):
    is_active: bool = False
    status: BrandStatus = "onboarding"


class BrandUpdate(BaseModel):
    name: str | None = None
    slug: str | None = None
    description: str | None = None
    website_url: str | None = None
    logo_url: str | None = None
    brand_guidelines: dict | None = None
    tone_of_voice: str | None = None
    target_audience: dict | None = None
    color_palette: dict | None = None
    is_active: bool | None = None
    status: BrandStatus | None = None
    is_bc_linked: bool | None = None
    bc_company: str | None = None
    bc_locations: list[str] | None = None
    bc_sync_vendor_nos: list[str] | None = None
    bc_sync_categories: list[str] | None = None


class ChannelConfigUpdate(BaseModel):
    """Payload for PUT /brands/{id}/channels."""

    channels: dict[str, dict] = {}


class BrandResponse(BrandBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    onboarding_completed_at: datetime | None = None
    activation_started_at: datetime | None = None
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
