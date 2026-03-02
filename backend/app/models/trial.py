from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql.sqltypes import JSON
from sqlalchemy.types import UserDefinedType

try:
    from pgvector.sqlalchemy import Vector as PGVector
except ModuleNotFoundError:
    class PGVector(UserDefinedType):
        cache_ok = True

        def __init__(self, dim: int) -> None:
            self.dim = dim

        def get_col_spec(self, **kwargs: object) -> str:
            return f"vector({self.dim})"

from app.database import Base
from app.models.enums import ConfidenceLevel, CriteriaType, Indication, JobStatus, TrialExtractionStatus, TrialStatus


class Trial(Base):
    __tablename__ = "trials"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    nct_id: Mapped[str | None] = mapped_column(String(32), index=True, nullable=True)
    ctg_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    trial_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    document_title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    ctg_match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    ctg_match_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    nickname: Mapped[str] = mapped_column(String(255), index=True)
    indication: Mapped[Indication | None] = mapped_column(
        Enum(Indication, name="indication", native_enum=False),
        nullable=True,
    )
    phase: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sponsor: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[TrialStatus] = mapped_column(Enum(TrialStatus, name="trial_status", native_enum=False), default=TrialStatus.draft)
    extraction_status: Mapped[TrialExtractionStatus] = mapped_column(
        Enum(TrialExtractionStatus, name="trial_extraction_status", native_enum=False),
        default=TrialExtractionStatus.needs_review,
    )
    extraction_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pi_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    coordinator_id: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )

    documents: Mapped[list["TrialDocument"]] = relationship(back_populates="trial", cascade="all, delete-orphan")


class TrialDocument(Base):
    __tablename__ = "trial_documents"
    __table_args__ = (UniqueConstraint("trial_id", "version", name="uq_trial_document_version"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trial_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer)
    filename: Mapped[str] = mapped_column(String(255))
    file_path: Mapped[str] = mapped_column(String(500))
    uploaded_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    trial: Mapped[Trial] = relationship(back_populates="documents")
    uploader: Mapped["User | None"] = relationship("User", foreign_keys=[uploaded_by], lazy="joined")

    @property
    def uploaded_by_email(self) -> str | None:
        return getattr(self.uploader, "email", None)


class TrialAmendment(Base):
    __tablename__ = "trial_amendments"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trial_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    from_version: Mapped[int] = mapped_column(Integer)
    to_version: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    uploader: Mapped["User | None"] = relationship("User", foreign_keys=[uploaded_by], lazy="joined")

    @property
    def uploaded_by_email(self) -> str | None:
        return getattr(self.uploader, "email", None)


class TrialCriteria(Base):
    __tablename__ = "trial_criteria"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trial_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    type: Mapped[CriteriaType] = mapped_column(Enum(CriteriaType, name="criteria_type", native_enum=False))
    text: Mapped[str] = mapped_column(Text)
    expression: Mapped[dict] = mapped_column(JSON)
    confidence: Mapped[ConfidenceLevel] = mapped_column(Enum(ConfidenceLevel, name="confidence_level", native_enum=False), default=ConfidenceLevel.needs_review)
    manual_review_required: Mapped[bool] = mapped_column(Boolean, default=True)
    approved_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rule_version: Mapped[str] = mapped_column(String(64))


class CtgSnapshot(Base):
    __tablename__ = "ctg_snapshots"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trial_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    nct_id: Mapped[str] = mapped_column(String(32), index=True)
    raw_json: Mapped[dict] = mapped_column(JSON)
    pulled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))


class ProtocolEmbedding(Base):
    __tablename__ = "protocol_embeddings"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    trial_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("trials.id", ondelete="CASCADE"), index=True)
    document_version: Mapped[int] = mapped_column(Integer)
    chunk_text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(PGVector(1536))
    chunk_index: Mapped[int] = mapped_column(Integer)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    type: Mapped[str] = mapped_column(String(100), index=True)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, name="job_status", native_enum=False), default=JobStatus.pending)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
