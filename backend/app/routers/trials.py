import logging
from pathlib import Path
from typing import Annotated
from urllib.parse import urlparse
from uuid import UUID

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user, require_role
from app.models.enums import Indication, JobStatus, TrialStatus, UserRole
from app.models.trial import BackgroundJob, Trial, TrialAmendment, TrialCriteria, TrialDocument
from app.models.user import User
from app.schemas.trial import TrialAmendmentRead, TrialCreate, TrialDocumentRead, TrialRead, TrialUpdate
from app.services.documents import extract_text, summarize_diff

router = APIRouter(prefix="/trials", tags=["trials"])
settings = get_settings()
logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = {".pdf", ".docx"}


def _is_allowed_file(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_SUFFIXES


async def _get_trial_or_404(db: AsyncSession, trial_id: UUID) -> Trial:
    result = await db.execute(select(Trial).where(Trial.id == trial_id))
    trial = result.scalar_one_or_none()
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")
    return trial


async def _enqueue_parse_job(job_id: UUID) -> None:
    await _enqueue_worker_job("parse_trial_document", str(job_id), extra={"job_id": str(job_id)})


async def _enqueue_embed_job(trial_id: UUID, document_version: int, file_path: str) -> None:
    await _enqueue_worker_job(
        "embed_protocol_document",
        str(trial_id),
        document_version,
        file_path,
        extra={"trial_id": str(trial_id), "document_version": document_version},
    )


async def _enqueue_worker_job(name: str, *args: object, extra: dict | None = None) -> None:
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
        await pool.aclose()
    except Exception:
        context = extra or {}
        logger.exception("Failed to enqueue ARQ job", extra={"job_name": name, **context})


async def _save_upload(trial_id: UUID, version: int, upload: UploadFile) -> tuple[str, str]:
    if not upload.filename or not _is_allowed_file(upload.filename):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Only PDF and DOCX uploads are allowed")

    trial_dir = Path(settings.uploads_dir) / str(trial_id)
    trial_dir.mkdir(parents=True, exist_ok=True)

    safe_name = upload.filename.replace("/", "_").replace("..", "_")
    target_name = f"v{version}_{safe_name}"
    target_path = trial_dir / target_name

    contents = await upload.read()
    target_path.write_bytes(contents)
    return safe_name, str(target_path)


@router.post("", response_model=TrialRead, status_code=status.HTTP_201_CREATED)
async def create_trial(
    payload: TrialCreate,
    user: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialRead:
    trial = Trial(
        nct_id=payload.nct_id,
        nickname=payload.nickname,
        indication=payload.indication,
        phase=payload.phase,
        sponsor=payload.sponsor,
        status=TrialStatus.draft,
        pi_id=payload.pi_id,
        coordinator_id=payload.coordinator_id,
        created_by=user.id,
    )
    db.add(trial)
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

    if payload.nickname is not None:
        trial.nickname = payload.nickname
    if payload.pi_id is not None:
        trial.pi_id = payload.pi_id
    if payload.coordinator_id is not None:
        trial.coordinator_id = payload.coordinator_id

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
    await _get_trial_or_404(db, trial_id)
    latest_result = await db.execute(
        select(TrialDocument).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    latest = latest_result.scalars().first()
    next_version = 1 if latest is None else latest.version + 1

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

    job = BackgroundJob(
        type="parse_trial_document",
        status=JobStatus.pending,
        payload={"trial_id": str(trial_id), "document_id": str(doc.id), "file_path": file_path},
    )
    db.add(job)
    await db.commit()
    await db.refresh(doc)
    await db.refresh(job)

    await _enqueue_parse_job(job.id)
    await _enqueue_embed_job(trial_id, next_version, file_path)
    return TrialDocumentRead.model_validate(doc)


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
    return [TrialDocumentRead.model_validate(row) for row in result.scalars().all()]


@router.get("/{trial_id}/documents/{document_id}/download")
async def download_trial_document(
    trial_id: UUID,
    document_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    await _get_trial_or_404(db, trial_id)
    result = await db.execute(
        select(TrialDocument).where(TrialDocument.id == document_id, TrialDocument.trial_id == trial_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")

    file_path = Path(document.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document file not found")

    return FileResponse(path=file_path, filename=document.filename, media_type="application/octet-stream")


@router.post("/{trial_id}/amendments", response_model=TrialAmendmentRead, status_code=status.HTTP_201_CREATED)
async def create_amendment(
    trial_id: UUID,
    upload: Annotated[UploadFile, File(...)],
    user: Annotated[User, Depends(require_role(UserRole.pi, UserRole.coordinator, UserRole.owner))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialAmendmentRead:
    await _get_trial_or_404(db, trial_id)

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

    old_text = extract_text(latest_doc.file_path)
    new_text = extract_text(file_path)
    summary = summarize_diff(old_text, new_text)

    amendment = TrialAmendment(
        trial_id=trial_id,
        from_version=latest_doc.version,
        to_version=next_version,
        summary=summary,
        uploaded_by=user.id,
    )
    db.add(amendment)
    await db.commit()
    await db.refresh(amendment)

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
