import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, field_validator

_VALID_OBJECTIVES = frozenset(
    {
        "awareness",
        "engagement",
        "traffic",
        "conversions",
        "product_launch",
        "seasonal",
        "event",
        "other",
    }
)


class CampaignBase(BaseModel):
    brand_id: uuid.UUID
    name: str
    description: str | None = None
    objective: str | None = None

    status: str = "draft"
    start_date: date | None = None
    end_date: date | None = None
    budget: dict | None = None
    target_channels: list[str] | None = None
    target_audience: dict | None = None
    kpis: dict | None = None

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_OBJECTIVES:
            raise ValueError(
                f"Invalid objective '{v}'. Must be one of: {', '.join(sorted(_VALID_OBJECTIVES))}"
            )
        return v


class CampaignCreate(CampaignBase):
    pass


class CampaignUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    objective: str | None = None
    status: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    budget: dict | None = None
    target_channels: list[str] | None = None
    target_audience: dict | None = None
    kpis: dict | None = None

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, v: str | None) -> str | None:
        if v is not None and v not in _VALID_OBJECTIVES:
            raise ValueError(
                f"Invalid objective '{v}'. Must be one of: {', '.join(sorted(_VALID_OBJECTIVES))}"
            )
        return v


class CampaignResponse(CampaignBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
