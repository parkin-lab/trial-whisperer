from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.enums import UserRole


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: EmailStr
    name: str
    role: UserRole
    active: bool
    domain: str
    created_at: datetime


class UserUpdate(BaseModel):
    role: UserRole | None = None
    active: bool | None = None


class DomainAllowlistCreate(BaseModel):
    domain: str


class DomainAllowlistRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    domain: str
    added_by: UUID | None
    added_at: datetime


class AdminStatsRead(BaseModel):
    total_users: int
    active_trials: int
    total_screens: int
    screens_this_month: int
    users_by_role: dict[str, int]
    trials_by_status: dict[str, int]
