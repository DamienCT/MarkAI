import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, computed_field


class CompetitorBase(BaseModel):
    brand_id: uuid.UUID
    name: str
    website_url: str | None = None
    social_handles: dict | None = None
    description: str | None = None
    monitoring_config: dict | None = None
    is_active: bool = True
    created_by: uuid.UUID | None = None


class CompetitorCreate(CompetitorBase):
    notes: str | None = None


class CompetitorCreateBody(BaseModel):
    """Body schema for creating a competitor via the API (brand_id comes from path)."""
    name: str
    website_url: str | None = None
    social_handles: dict | None = None
    description: str | None = None
    notes: str | None = None


class CompetitorUpdate(BaseModel):
    name: str | None = None
    website_url: str | None = None
    social_handles: dict | None = None
    description: str | None = None
    notes: str | None = None
    monitoring_config: dict | None = None
    is_active: bool | None = None


class CompetitorResponse(CompetitorBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    @computed_field  # type: ignore[prop-decorator]
    @property
    def notes(self) -> str | None:
        """Alias description as notes for frontend compatibility."""
        return self.description
