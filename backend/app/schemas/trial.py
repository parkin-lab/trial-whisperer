from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.models.enums import Indication, TrialStatus


class TrialCreate(BaseModel):
    nct_id: str | None = None
    nickname: str
    indication: Indication
    phase: str | None = None
    sponsor: str | None = None
    pi_id: UUID | None = None
    coordinator_id: UUID | None = None


class TrialUpdate(BaseModel):
    nickname: str | None = None
    pi_id: UUID | None = None
    coordinator_id: UUID | None = None


class TrialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nct_id: str | None
    nickname: str
    indication: Indication
    phase: str | None
    sponsor: str | None
    status: TrialStatus
    pi_id: UUID | None
    coordinator_id: UUID | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class TrialDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trial_id: UUID
    version: int
    filename: str
    file_path: str
    uploaded_by: UUID
    uploaded_at: datetime


class TrialAmendmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trial_id: UUID
    from_version: int
    to_version: int
    summary: str
    uploaded_by: UUID
    uploaded_at: datetime


class CtgSnapshotCreate(BaseModel):
    nct_id: str


class CtgSnapshotRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trial_id: UUID
    nct_id: str
    raw_json: dict
    pulled_at: datetime
