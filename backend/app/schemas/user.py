import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class UserBase(BaseModel):
    email: str
    display_name: str
    role: str = "viewer"
    is_active: bool = False


class UserCreate(UserBase):
    entra_id: str


class UserUpdate(BaseModel):
    display_name: str | None = None
    avatar_url: str | None = None
    role: str | None = None
    is_active: bool | None = None


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    entra_id: str
    avatar_url: str | None = None
    last_login_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
