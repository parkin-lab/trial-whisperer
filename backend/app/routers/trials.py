import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.enums import Indication, JobStatus, TrialExtractionStatus, TrialStatus, UserRole
from app.models.trial import BackgroundJob, Trial, TrialAmendment, TrialCriteria, TrialDocument
from app.models.user import User
from app.schemas.trial import TrialAmendmentRead, TrialCreate, TrialDocumentRead, TrialRead, TrialUpdate
from app.services.documents import extract_text, summarize_diff
from app.services.storage import (
    download_file as storage_download_file,
    get_local_path_for_extraction,
    upload_file as storage_upload_file,
)

router = APIRouter(prefix="/trials", tags=["trials"])
settings = get_settings()
logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".docx"}


def _is_allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_SUFFIXES


def _build_ctg_url(nct_id: str | None) -> str | None:
    if not nct_id:
        return None
    return f"https://clinicaltrials.gov/study/{nct_id}"


def _mark_extraction_processing(trial: Trial) -> None:
    trial.extraction_status = TrialExtractionStatus.processing
    trial.extraction_started_at = datetime.now(UTC)
    trial.extraction_completed_at = None


async def _get_trial_or_404(db: AsyncSession, trial_id: UUID) -> Trial:
    result = await db.execute(select(Trial).where(Trial.id == trial_id))
    trial = result.scalar_one_or_none()
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")
    return trial


def _to_trial_document_read(document: TrialDocument) -> TrialDocumentRead:
    payload = TrialDocumentRead.model_validate(document).model_dump()
    payload["download_url"] = f"/trials/{document.trial_id}/documents/{document.id}/download"
    return TrialDocumentRead.model_validate(payload)


async def _enqueue_parse_job(job_id: UUID) -> bool:
    return await _enqueue_worker_job("parse_trial_document", str(job_id), extra={"job_id": str(job_id)})


async def _enqueue_worker_job(name: str, *args: object, extra: dict | None = None) -> bool:
    pool = None
    try:
        if hasattr(RedisSettings, "from_dsn"):
            redis_settings = RedisSettings.from_dsn(settings.redis_url)
        else:
            parsed = urlparse(settings.redis_url)
            db = int((parsed.path or "/0").replace("/", "") or "0")
            redis_settings = RedisSettings(
                host=parsed.hostname or "localhost",
                port=parsed.port or 6379,
                database=db,
                password=parsed.password,
            )
        pool = await create_pool(redis_settings)
        await pool.enqueue_job(name, *args)
        return True
    except Exception:
        context = extra or {}
        logger.exception("Failed to enqueue ARQ job", extra={"job_name": name, **context})
        return False
    finally:
        if pool is not None:
            await pool.aclose()


async def _save_upload(trial_id: UUID, version: int, upload: UploadFile) -> tuple[str, str]:
    if not upload.filename or not _is_allowed_file(upload.filename):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only PDF and DOCX uploads are allowed")

    MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB
    contents = await upload.read(MAX_UPLOAD_BYTES + 1)
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="File too large (max 50 MB)",
        )

    safe_name = Path(upload.filename).name.replace(" ", "_")
    storage_path = await storage_upload_file(str(trial_id), version, safe_name, contents)
    return safe_name, storage_path


@router.post("", response_model=TrialRead, status_code=status.HTTP_201_CREATED)
async def create_trial(
    payload: TrialCreate,
    user: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    trial = Trial(
        nct_id=payload.nct_id,
        ctg_url=payload.ctg_url or _build_ctg_url(payload.nct_id),
        nickname=payload.nickname,
        indication=payload.indication,
        phase=payload.phase,
        sponsor=payload.sponsor,
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.needs_review,
        pi_id=payload.pi_id,
        coordinator_id=payload.coordinator_id,
        created_by=user.id,
    )
    db.add(trial)
    await db.commit()
    await db.refresh(trial)
    return TrialRead.model_validate(trial)


@router.post("/create-with-upload", response_model=TrialRead, status_code=status.HTTP_201_CREATED)
async def create_trial_with_upload(
    nickname: Annotated[str, Form(min_length=1)],
    protocol: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    cleaned_nickname = nickname.strip()
    if not cleaned_nickname:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Nickname is required")

    trial = Trial(
        nickname=cleaned_nickname,
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.processing,
        extraction_started_at=datetime.now(UTC),
        created_by=user.id,
    )
    db.add(trial)
    await db.flush()

    filename, file_path = await _save_upload(trial.id, 1, protocol)
    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename=filename,
        file_path=file_path,
        uploaded_by=user.id,
    )
    db.add(doc)
    await db.flush()

    parse_job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial.id), "document_id": str(doc.id), "file_path": file_path},
    )
    db.add(parse_job)
    await db.commit()
    await db.refresh(trial)
    await db.refresh(parse_job)

    if not await _enqueue_parse_job(parse_job.id):
        parse_job.status = JobStatus.failed
        parse_job.error = "Failed to enqueue job"
        trial.extraction_status = TrialExtractionStatus.needs_review
        trial.extraction_completed_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(trial)

    return TrialRead.model_validate(trial)


@router.get("", response_model=list[TrialRead])
async def list_trials(
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    status_value: TrialStatus | None = Query(default=None, alias="status"),
    indication: Indication | None = None,
) -> list[TrialRead]:
    query: Select[tuple[Trial]] = select(Trial).order_by(Trial.created_at.desc())
    if status_value is not None:
        query = query.where(Trial.status == status_value)
    if indication is not None:
        query = query.where(Trial.indication == indication)

    result = await db.execute(query)
    return [TrialRead.model_validate(trial) for trial in result.scalars().all()]


@router.get("/{trial_id}", response_model=TrialRead)
async def get_trial(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    trial = await _get_trial_or_404(db, trial_id)
    return TrialRead.model_validate(trial)


@router.patch("/{trial_id}", response_model=TrialRead)
async def update_trial(
    trial_id: UUID,
    payload: TrialUpdate,
    _: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    trial = await _get_trial_or_404(db, trial_id)

    updates = payload.model_dump(exclude_unset=True)
    if "status" in updates and updates["status"] == TrialStatus.active:
        indication_value = updates.get("indication", trial.indication)
        if indication_value is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Cannot activate trial without indication",
            )
        criteria_result = await db.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial_id))
        criteria_rows = criteria_result.scalars().all()
        blocking = [c for c in criteria_rows if c.approved_at is None and not c.manual_review_required]
        if blocking:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"{len(blocking)} criteria must be approved before activating this trial",
            )

    for field in {"nickname", "nct_id", "ctg_url", "indication", "phase", "sponsor", "pi_id", "coordinator_id", "status"}:
        if field in updates:
            setattr(trial, field, updates[field])

    if "nct_id" in updates and "ctg_url" not in updates:
        trial.ctg_url = _build_ctg_url(trial.nct_id)

    await db.commit()
    await db.refresh(trial)
    return TrialRead.model_validate(trial)


@router.post("/{trial_id}/archive", response_model=TrialRead)
async def archive_trial(
    trial_id: UUID,
    _: Annotated[User, Depends(require_role(UserRole.pi, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    trial = await _get_trial_or_404(db, trial_id)
    trial.status = TrialStatus.archived
    await db.commit()
    await db.refresh(trial)
    return TrialRead.model_validate(trial)


@router.post("/{trial_id}/activate", response_model=TrialRead)
async def activate_trial(
    trial_id: UUID,
    _: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    trial = await _get_trial_or_404(db, trial_id)
    if trial.indication is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot activate trial without indication",
        )

    criteria_result = await db.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial_id))
    criteria = criteria_result.scalars().all()
    if not criteria:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot activate trial without eligibility criteria",
        )

    blocking_count = sum(1 for item in criteria if item.approved_at is None and not item.manual_review_required)
    if blocking_count > 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Cannot activate trial until all criteria are approved or flagged for manual review",
        )

    trial.status = TrialStatus.active
    await db.commit()
    await db.refresh(trial)
    return TrialRead.model_validate(trial)


@router.delete("/{trial_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_trial(
    trial_id: UUID,
    _: Annotated[User, Depends(require_role(UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    trial = await _get_trial_or_404(db, trial_id)
    await db.delete(trial)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{trial_id}/documents", response_model=TrialDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_trial_document(
    trial_id: UUID,
    upload: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialDocumentRead:
    trial = await _get_trial_or_404(db, trial_id)
    latest_doc_result = await db.execute(
        select(TrialDocument)
        .where(TrialDocument.trial_id == trial_id)
        .order_by(TrialDocument.version.desc())
        .with_for_update()
    )
    latest_doc = latest_doc_result.scalars().first()
    next_version = (latest_doc.version + 1) if latest_doc else 1

    filename, file_path = await _save_upload(trial_id, next_version, upload)

    doc = TrialDocument(
        trial_id=trial_id,
        version=next_version,
        filename=filename,
        file_path=file_path,
        uploaded_by=user.id,
    )
    db.add(doc)
    await db.flush()

    parse_job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial_id), "document_id": str(doc.id), "file_path": file_path},
    )
    db.add(parse_job)
    _mark_extraction_processing(trial)

    await db.commit()
    await db.refresh(doc)
    await db.refresh(parse_job)

    jobs_to_update: list[BackgroundJob] = []
    if not await _enqueue_parse_job(parse_job.id):
        parse_job.status = JobStatus.failed
        parse_job.error = "Failed to enqueue job"
        trial.extraction_status = TrialExtractionStatus.needs_review
        trial.extraction_completed_at = datetime.now(UTC)
        jobs_to_update.append(parse_job)

    if jobs_to_update:
        await db.commit()

    return _to_trial_document_read(doc)


@router.get("/{trial_id}/documents", response_model=list[TrialDocumentRead])
async def list_trial_documents(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TrialDocumentRead]:
    await _get_trial_or_404(db, trial_id)
    result = await db.execute(
        select(TrialDocument).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    return [_to_trial_document_read(row) for row in result.scalars().all()]


@router.get("/{trial_id}/documents/{document_id}/download")
async def download_trial_document(
    trial_id: UUID,
    document_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    await _get_trial_or_404(db, trial_id)
    result = await db.execute(
        select(TrialDocument).where(TrialDocument.id == document_id, TrialDocument.trial_id == trial_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    try:
        contents, filename = await storage_download_file(document.file_path)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found") from None

    return Response(
        content=contents,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{trial_id}/amendments", response_model=TrialAmendmentRead, status_code=status.HTTP_201_CREATED)
async def create_amendment(
    trial_id: UUID,
    upload: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialAmendmentRead:
    trial = await _get_trial_or_404(db, trial_id)

    latest_result = await db.execute(
        select(TrialDocument).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    latest_doc = latest_result.scalars().first()
    if latest_doc is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Upload an initial document first")

    next_version = latest_doc.version + 1
    filename, file_path = await _save_upload(trial_id, next_version, upload)

    new_doc = TrialDocument(
        trial_id=trial_id,
        version=next_version,
        filename=filename,
        file_path=file_path,
        uploaded_by=user.id,
    )
    db.add(new_doc)
    await db.flush()

    old_contents, _ = await storage_download_file(latest_doc.file_path)
    new_contents, _ = await storage_download_file(file_path)
    old_tmp_path = get_local_path_for_extraction(latest_doc.file_path, old_contents)
    new_tmp_path = get_local_path_for_extraction(file_path, new_contents)
    old_text = extract_text(old_tmp_path)
    new_text = extract_text(new_tmp_path)

    summary = summarize_diff(old_text, new_text)

    amendment = TrialAmendment(
        trial_id=trial_id,
        from_version=latest_doc.version,
        to_version=next_version,
        summary=summary,
        uploaded_by=user.id,
    )
    db.add(amendment)
    parse_job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial_id), "document_id": str(new_doc.id), "file_path": file_path},
    )
    db.add(parse_job)
    _mark_extraction_processing(trial)
    await db.commit()
    await db.refresh(amendment)
    await db.refresh(parse_job)

    jobs_to_update: list[BackgroundJob] = []
    if not await _enqueue_parse_job(parse_job.id):
        parse_job.status = JobStatus.failed
        parse_job.error = "Failed to enqueue job"
        trial.extraction_status = TrialExtractionStatus.needs_review
        trial.extraction_completed_at = datetime.now(UTC)
        jobs_to_update.append(parse_job)

    if jobs_to_update:
        await db.commit()

    return TrialAmendmentRead.model_validate(amendment)


@router.get("/{trial_id}/amendments", response_model=list[TrialAmendmentRead])
async def list_amendments(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TrialAmendmentRead]:
    await _get_trial_or_404(db, trial_id)
    result = await db.execute(
        select(TrialAmendment).where(TrialAmendment.trial_id == trial_id).order_by(TrialAmendment.uploaded_at.desc())
    )
    return [TrialAmendmentRead.model_validate(row) for row in result.scalars().all()]
