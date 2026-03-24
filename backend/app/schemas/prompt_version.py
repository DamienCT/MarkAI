import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class PromptVersionBase(BaseModel):
    name: str
    slug: str
    category: str
    template: str
    variables: dict | None = None
    version: int
    is_active: bool = False
    performance_score: Decimal | None = None
    a_b_group: str | None = None


class PromptVersionCreate(PromptVersionBase):
    pass


class PromptVersionUpdate(BaseModel):
    name: str | None = None
    template: str | None = None
    variables: dict | None = None
    is_active: bool | None = None
    performance_score: Decimal | None = None
    a_b_group: str | None = None


class PromptVersionResponse(PromptVersionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
