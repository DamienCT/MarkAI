import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class AIModelCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    display_name: str
    description: str | None = None
    active_model: "AIModelResponse | None" = None


class AIModelResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    model_id: str
    display_name: str | None = None
    category_id: uuid.UUID | None = None
    is_available: bool = True
    capabilities: dict = {}
    discovered_at: datetime


class AIModelSelectionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    category_slug: str
    model_id: uuid.UUID
    is_active: bool = True
    priority: int = 0
    set_at: datetime


class AIModelSelectionUpdate(BaseModel):
    model_id: uuid.UUID
    is_active: bool = True
    priority: int = 0


class ActiveModelsResponse(BaseModel):
    """Maps category_slug to the active model_id string (e.g. 'gpt-4o')."""
    models: dict[str, str] = {}


class DiscoverModelsResponse(BaseModel):
    discovered: int
    updated: int
    unavailable: int
