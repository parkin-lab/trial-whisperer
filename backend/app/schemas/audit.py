from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr


class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID | None
    user_email: EmailStr | None = None
    timestamp: datetime
    indication: str
    criteria_version_hash: str
    engine_version: str
    screen_results: dict[str, dict[str, Any]]
    exported_at: datetime | None


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int
    limit: int
    offset: int


class AuditLogFilters(BaseModel):
    user_id: UUID | None = None
    indication: str | None = None
    from_date: datetime | date | None = None
    to_date: datetime | date | None = None
    trial_id: UUID | None = None
    limit: int | None = None
    offset: int | None = None


class AuditPurgeResponse(BaseModel):
    deleted: int
