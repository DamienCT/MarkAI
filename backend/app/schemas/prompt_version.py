import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

_VALID_AB_GROUPS = frozenset({"A", "B"})


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

    @field_validator("a_b_group")
    @classmethod
    def validate_a_b_group(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_AB_GROUPS:
            raise ValueError(f"Invalid a_b_group '{v}'. Must be 'A' or 'B'.")
        return v


class PromptVersionCreate(PromptVersionBase):
    pass


class PromptVersionUpdate(BaseModel):
    name: str | None = None
    template: str | None = None
    variables: dict | None = None
    is_active: bool | None = None
    performance_score: Decimal | None = None
    a_b_group: str | None = None

    @field_validator("a_b_group")
    @classmethod
    def validate_a_b_group(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_AB_GROUPS:
            raise ValueError(f"Invalid a_b_group '{v}'. Must be 'A' or 'B'.")
        return v


class PromptVersionResponse(PromptVersionBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
