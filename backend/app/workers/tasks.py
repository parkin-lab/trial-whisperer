import logging
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.enums import JobStatus
from app.models.trial import BackgroundJob

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
            job.status = JobStatus.running
            await session.commit()

            job.status = JobStatus.completed
            job.completed_at = datetime.now(UTC)
            await session.commit()
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await session.commit()
            logger.exception("Background job failed", extra={"job_id": job_id})


class WorkerSettings:
    functions = [parse_trial_document]
    redis_settings = _redis_settings_from_dsn(settings.redis_url)
