import logging
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.enums import JobStatus, TrialExtractionStatus
from app.models.trial import BackgroundJob, Trial
from app.services.documents import extract_text
from app.services.storage import download_file as storage_download_file, get_local_path_for_extraction
from app.services.trial_metadata import extract_trial_metadata_from_text

logger = logging.getLogger(__name__)
settings = get_settings()


def _redis_settings_from_dsn(dsn: str) -> RedisSettings:
    parsed = urlparse(dsn)
    db = int((parsed.path or "/0").replace("/", "") or "0")
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=db,
        password=parsed.password,
    )


async def parse_trial_document(ctx: dict, job_id: str) -> None:
    del ctx
    try:
        job_uuid = UUID(job_id)
    except ValueError:
        logger.error("Invalid background job id", extra={"job_id": job_id})
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_uuid))
        job = result.scalar_one_or_none()
        if job is None:
            logger.error("Background job not found", extra={"job_id": job_id})
            return

        try:
            payload = job.payload or {}
            trial_id_raw = payload.get("trial_id")
            file_path = payload.get("file_path")
            if not trial_id_raw or not file_path:
                raise ValueError("Background job payload missing trial_id or file_path")

            trial_id = UUID(trial_id_raw)
            trial_result = await session.execute(select(Trial).where(Trial.id == trial_id))
            trial = trial_result.scalar_one_or_none()
            if trial is None:
                raise ValueError("Trial not found for parse job")

            job.status = JobStatus.running
            trial.extraction_status = TrialExtractionStatus.processing
            trial.extraction_started_at = trial.extraction_started_at or datetime.now(UTC)
            trial.extraction_completed_at = None
            await session.commit()

            contents, _ = await storage_download_file(file_path)
            local_path = get_local_path_for_extraction(file_path, contents)
            text = extract_text(local_path)
            metadata = await extract_trial_metadata_from_text(text)

            if trial.indication is None and metadata.indication is not None:
                trial.indication = metadata.indication
            if not trial.nct_id and metadata.nct_id:
                trial.nct_id = metadata.nct_id
            if not trial.ctg_url and metadata.ctg_url:
                trial.ctg_url = metadata.ctg_url
            if not trial.sponsor and metadata.sponsor:
                trial.sponsor = metadata.sponsor
            if not trial.phase and metadata.phase:
                trial.phase = metadata.phase

            has_core_fields = bool(trial.indication and trial.nct_id and trial.sponsor and trial.phase)
            trial.extraction_status = TrialExtractionStatus.ready if has_core_fields else TrialExtractionStatus.needs_review
            trial.extraction_completed_at = datetime.now(UTC)
            job.status = JobStatus.completed
            job.completed_at = datetime.now(UTC)
            await session.commit()
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            try:
                payload = job.payload or {}
                trial_id_raw = payload.get("trial_id")
                if trial_id_raw:
                    trial_result = await session.execute(select(Trial).where(Trial.id == UUID(trial_id_raw)))
                    trial = trial_result.scalar_one_or_none()
                    if trial is not None:
                        trial.extraction_status = TrialExtractionStatus.needs_review
                        trial.extraction_completed_at = datetime.now(UTC)
            except Exception:
                logger.exception("Failed to update extraction status on parse error", extra={"job_id": job_id})
            await session.commit()
            logger.exception("Background job failed", extra={"job_id": job_id})


class WorkerSettings:
    functions = [parse_trial_document]
    redis_settings = _redis_settings_from_dsn(settings.redis_url)
