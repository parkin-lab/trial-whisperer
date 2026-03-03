from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.engine.evaluator import TrialResult
from app.models.enums import ConfidenceLevel, CriteriaType, Indication, TrialExtractionStatus, TrialStatus


class TrialCreate(BaseModel):
    nct_id: str | None = None
    ctg_url: str | None = None
    trial_title: str | None = None
    document_title: str | None = None
    ctg_match_confidence: float | None = None
    ctg_match_note: str | None = None
    nickname: str
    indication: Indication | None = None
    phase: str | None = None
    sponsor: str | None = None
    pi_id: UUID | None = None
    coordinator_id: UUID | None = None


class TrialUpdate(BaseModel):
    nickname: str | None = None
    nct_id: str | None = None
    ctg_url: str | None = None
    trial_title: str | None = None
    document_title: str | None = None
    ctg_match_confidence: float | None = None
    ctg_match_note: str | None = None
    indication: Indication | None = None
    phase: str | None = None
    sponsor: str | None = None
    pi_id: UUID | None = None
    coordinator_id: UUID | None = None
    status: TrialStatus | None = None


class TrialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nct_id: str | None
    ctg_url: str | None
    ctg_candidate_nct_id: str | None
    ctg_candidate_url: str | None
    ctg_candidate_title: str | None
    ctg_candidate_source: str | None
    ctg_candidate_pool: list[dict[str, Any]] | None
    trial_title: str | None
    document_title: str | None
    ctg_match_confidence: float | None
    ctg_match_note: str | None
    nickname: str
    indication: Indication | None
    phase: str | None
    sponsor: str | None
    status: TrialStatus
    extraction_status: TrialExtractionStatus
    extraction_started_at: datetime | None
    extraction_completed_at: datetime | None
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
    download_url: str | None = None
    uploaded_by: UUID
    uploaded_by_email: str | None = None
    uploaded_at: datetime


class TrialAmendmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    trial_id: UUID
    from_version: int
    to_version: int
    summary: str
    uploaded_by: UUID
    uploaded_by_email: str | None = None
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


class CtgCandidateRead(BaseModel):
    nct_id: str
    title: str | None = None
    url: str | None = None
    confidence: float | None = None
    source: str | None = None


class CtgCandidateAcceptRequest(BaseModel):
    nct_id: str | None = None
    title: str | None = None
    url: str | None = None
    source: str | None = None
    confidence: float | None = None


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


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    document_version: int | None = None
    mode: Literal["brief", "detailed"] = "brief"

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question cannot be empty")
        return cleaned


class QAResponse(BaseModel):
    answer: str | None
    sources: list[dict[str, Any]]
    embeddings_pending: bool
    model: str


class ScreeningRequest(BaseModel):
    indication: Indication
    patient_data: dict[str, Any]
    trial_ids: list[UUID] | None = None


class ScreeningResponse(BaseModel):
    results: list[TrialResult]
    screened_at: datetime
    engine_version: str
