from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.engine.evaluator import TrialResult
from app.models.enums import ConfidenceLevel, CriteriaType, Indication, TrialStatus


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


class ParsedCriterion(BaseModel):
    type: CriteriaType
    text: str
    expression: dict[str, Any]
    confidence: ConfidenceLevel = ConfidenceLevel.needs_review
    manual_review_required: bool = True


class TrialCriterionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trial_id: UUID
    document_version: int
    type: CriteriaType
    text: str
    expression: dict[str, Any]
    confidence: ConfidenceLevel
    manual_review_required: bool
    approved_by: UUID | None
    approved_at: datetime | None
    rule_version: str


class TrialCriterionUpdate(BaseModel):
    text: str | None = None
    expression: dict[str, Any] | None = None
    manual_review_required: bool | None = None
    approve: bool | None = None


class CriteriaReviewStatusRead(BaseModel):
    total: int
    approved: int
    needs_review: int
    blocking_count: int


class ScreeningRequest(BaseModel):
    indication: Indication
    patient_data: dict[str, Any]
    trial_ids: list[UUID] | None = None


class ScreeningResponse(BaseModel):
    results: list[TrialResult]
    screened_at: datetime
    engine_version: str
