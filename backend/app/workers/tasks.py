import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.enums import JobStatus, TrialExtractionStatus
from app.models.trial import BackgroundJob, Trial
from app.services.ctg import search_studies
from app.services.documents import extract_text
from app.services.storage import download_file as storage_download_file, get_local_path_for_extraction
from app.services.trial_metadata import extract_trial_metadata_from_text

logger = logging.getLogger(__name__)
settings = get_settings()
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def _redis_settings_from_dsn(dsn: str) -> RedisSettings:
    parsed = urlparse(dsn)
    db = int((parsed.path or "/0").replace("/", "") or "0")
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=db,
        password=parsed.password,
    )


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = re.sub(r"[^a-z0-9]+", " ", value.lower())
    return re.sub(r"\s+", " ", normalized).strip()


def _tokenize(value: str | None) -> set[str]:
    return {token for token in TOKEN_PATTERN.findall(_normalize_text(value)) if len(token) > 2}


def _has_high_title_similarity(left: str | None, right: str | None) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return False
    if left_norm in right_norm or right_norm in left_norm:
        return True

    left_tokens = _tokenize(left_norm)
    right_tokens = _tokenize(right_norm)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / min(len(left_tokens), len(right_tokens))
    return overlap >= 0.6


def _phase_matches(left: str | None, right: str | None) -> bool:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return False
    return left_norm in right_norm or right_norm in left_norm


def _has_sponsor_overlap(left: str | None, right: str | None) -> bool:
    left_tokens = _tokenize(left)
    right_tokens = _tokenize(right)
    if not left_tokens or not right_tokens:
        return False
    return bool(left_tokens & right_tokens)


def _compute_ctg_match_confidence(
    trial_title: str | None,
    trial_phase: str | None,
    trial_sponsor: str | None,
    candidate_title: str | None,
    candidate_phase: str | None,
    candidate_sponsor: str | None,
) -> float:
    confidence = 0.0
    if _has_high_title_similarity(trial_title, candidate_title):
        confidence += 0.5
    if _phase_matches(trial_phase, candidate_phase):
        confidence += 0.3
    if _has_sponsor_overlap(trial_sponsor, candidate_sponsor):
        confidence += 0.2
    return min(confidence, 1.0)


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
            if not trial.trial_title and metadata.trial_title:
                trial.trial_title = metadata.trial_title
            if not trial.sponsor and metadata.sponsor:
                trial.sponsor = metadata.sponsor
            if not trial.phase and metadata.phase:
                trial.phase = metadata.phase

            if not trial.nct_id and trial.trial_title:
                try:
                    ctg_candidates = await search_studies(trial.trial_title)
                except Exception:
                    logger.exception("CTG title search failed", extra={"trial_id": str(trial.id)})
                    trial.ctg_match_note = "CTG title search failed"
                else:
                    top_candidate = ctg_candidates[0] if ctg_candidates else None
                    if top_candidate is None:
                        trial.ctg_match_confidence = 0.0
                        trial.ctg_match_note = "No CTG match found from title search"
                    else:
                        confidence = _compute_ctg_match_confidence(
                            trial_title=trial.trial_title,
                            trial_phase=trial.phase,
                            trial_sponsor=trial.sponsor,
                            candidate_title=top_candidate.get("officialTitle"),
                            candidate_phase=top_candidate.get("phase"),
                            candidate_sponsor=top_candidate.get("sponsor"),
                        )
                        trial.ctg_match_confidence = confidence
                        if confidence >= 0.75 and top_candidate.get("nctId"):
                            trial.nct_id = top_candidate["nctId"]
                            trial.ctg_url = f"https://clinicaltrials.gov/study/{trial.nct_id}"
                            trial.ctg_match_note = "Auto-matched from title search"
                        else:
                            trial.ctg_match_note = "Candidate found; manual review recommended"

            has_ctg_link = bool(trial.nct_id or ((trial.ctg_match_confidence or 0.0) >= 0.75))
            has_core_fields = bool(trial.indication and trial.sponsor and trial.phase and has_ctg_link)
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
