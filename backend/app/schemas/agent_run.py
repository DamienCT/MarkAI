import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

AgentRunTrigger = Literal["scheduled", "manual", "event", "webhook", "activation"]


class AgentRunBase(BaseModel):
    agent_type: str
    trigger: AgentRunTrigger
    brand_id: uuid.UUID


class AgentRunCreate(AgentRunBase):
    input_payload: dict | None = None
    prompt_version_id: uuid.UUID | None = None
    initiated_by: uuid.UUID | None = None


class AgentRunResponse(AgentRunBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    input_payload: dict | None = None
    output_payload: dict | None = None
    error_message: str | None = None
    tokens_used: int | None = None
    cost_usd: Decimal | None = None
    duration_ms: int | None = None
    prompt_version_id: uuid.UUID | None = None
    initiated_by: uuid.UUID | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
