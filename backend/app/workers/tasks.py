import asyncio
import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.engine.schema import validate_expression
from app.models.enums import ConfidenceLevel, CriteriaParseStatus, JobStatus, TrialExtractionStatus
from app.models.trial import BackgroundJob, Trial, TrialCriteria, TrialDocument
from app.services.criteria_parser import parse_criteria_from_text, parse_criteria_with_ai_from_text
from app.services.ctg import fetch_study, first_study_result, search_studies, search_web
from app.services.ctg_resolver import (
    build_keyword_queries,
    extract_nct_from_text,
    generate_title_variants,
    score_candidate,
)
from app.services.ctg_semantic import build_protocol_summary_context, count_core_reason_codes, score_candidate_semantic
from app.services.documents import extract_text
from app.services.storage import download_file as storage_download_file, get_local_path_for_extraction
from app.services.trial_metadata import extract_trial_metadata_from_text

logger = logging.getLogger(__name__)
settings = get_settings()
CTG_AUTOFILL_FINAL_SCORE = 0.85
CTG_AUTO_ACCEPT_MIN_CORE_SIGNALS = 2
CTG_LEXICAL_WEIGHT = 0.10
CTG_SEMANTIC_WEIGHT = 0.90
CTG_TITLE_CANDIDATE_LIMIT = 3
CTG_QUERY_RESULT_LIMIT = 3
CTG_WEB_RESULT_LIMIT = 5
CTG_CANDIDATE_POOL_LIMIT = 5
CTG_SOURCE_TITLE = "title"
CTG_SOURCE_VARIANT = "variant"
CTG_SOURCE_KEYWORD = "keyword"
CTG_SOURCE_WEB = "web"
CTG_MATCH_NOTES_BY_SOURCE = {
    CTG_SOURCE_TITLE: "Auto-matched from CTG title search",
    CTG_SOURCE_VARIANT: "Auto-matched from CTG title variant search",
    CTG_SOURCE_KEYWORD: "Auto-matched from CTG keyword search",
    CTG_SOURCE_WEB: "Auto-matched from CTG web fallback",
}
CTG_SOURCE_PRIORITY = {
    CTG_SOURCE_TITLE: 4,
    CTG_SOURCE_VARIANT: 3,
    CTG_SOURCE_KEYWORD: 2,
    CTG_SOURCE_WEB: 1,
}
ENGINE_RULE_VERSION = "1.0.0"


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


def _ordered_unique_titles(values: list[str | None]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value:
            continue
        title = value.strip()
        if not title:
            continue
        key = _normalize_text(title)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(title)
    return deduped


def _clear_ctg_candidate_fields(trial: Trial) -> None:
    trial.ctg_candidate_nct_id = None
    trial.ctg_candidate_url = None
    trial.ctg_candidate_title = None
    trial.ctg_candidate_source = None


def _candidate_title(candidate: dict) -> str | None:
    title_value = candidate.get("title") or candidate.get("officialTitle") or candidate.get("briefTitle")
    if not title_value:
        return None
    return str(title_value).strip()[:500] or None


def _clamp_score(value: float | int | None) -> float:
    if value is None:
        return 0.0
    try:
        score = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, score))


def _blend_score(lexical_score: float, semantic_score: float) -> float:
    blended = (CTG_LEXICAL_WEIGHT * _clamp_score(lexical_score)) + (CTG_SEMANTIC_WEIGHT * _clamp_score(semantic_score))
    return _clamp_score(blended)


def _candidate_sort_tuple(item: dict) -> tuple[float, float, float]:
    return (
        _clamp_score(item.get("final_score")),
        _clamp_score(item.get("semantic_score")),
        _clamp_score(item.get("lexical_score")),
    )


def _build_candidate_pool(candidate_by_nct: dict[str, dict]) -> list[dict]:
    ranked = sorted(candidate_by_nct.values(), key=_candidate_sort_tuple, reverse=True)[:CTG_CANDIDATE_POOL_LIMIT]
    pool: list[dict] = []
    for item in ranked:
        nct_id = str(item.get("nct_id") or "").strip()
        if not nct_id:
            continue
        pool.append(
            {
                "nct_id": nct_id,
                "title": _candidate_title(item),
                "url": item.get("url") or f"https://clinicaltrials.gov/study/{nct_id}",
                "source": item.get("source"),
                "lexical_score": _clamp_score(item.get("lexical_score")),
                "semantic_score": _clamp_score(item.get("semantic_score")),
                "final_score": _clamp_score(item.get("final_score")),
                "reason_codes": [str(code) for code in (item.get("reason_codes") or []) if str(code).strip()],
                "notes": str(item.get("notes") or "").strip()[:200] or None,
            }
        )
    return pool


def _manual_review_note(best_candidate: dict | None) -> str:
    if not best_candidate:
        return "No CTG match found from resolver ladder"

    nct_id = str(best_candidate.get("nct_id") or "").strip()
    final_score = _clamp_score(best_candidate.get("final_score"))
    core_signal_count = count_core_reason_codes(best_candidate.get("reason_codes") or [])

    if final_score < CTG_AUTOFILL_FINAL_SCORE:
        return (
            f"Top CTG candidate {nct_id or 'N/A'} scored {final_score:.2f}; "
            f"below auto-accept threshold {CTG_AUTOFILL_FINAL_SCORE:.2f}. Manual review required."
        )

    return (
        f"Top CTG candidate {nct_id or 'N/A'} scored {final_score:.2f}, but only {core_signal_count} "
        "core signal(s) among disease/intervention/phase. Manual review required."
    )


async def _upsert_parsed_criteria(
    *,
    session,
    trial_id: UUID,
    document_version: int,
    text: str,
) -> int:
    await session.execute(
        delete(TrialCriteria).where(
            TrialCriteria.trial_id == trial_id,
            TrialCriteria.document_version == document_version,
        )
    )

    # Match the prior user-facing "Extract Criteria" behavior: AI-first extraction,
    # then deterministic fallback when AI returns no rows.
    parsed = await parse_criteria_with_ai_from_text(text)
    if not parsed:
        parsed = await parse_criteria_from_text(text)
    if not parsed:
        logger.info(
            "Criteria parser returned no rows",
            extra={"trial_id": str(trial_id), "document_version": document_version},
        )
        return 0

    inserted_count = 0
    for item in parsed:
        criterion_text = item.text or ""
        if not criterion_text.strip():
            continue

        expression_payload = item.expression
        confidence_value = item.confidence
        manual_review_required = item.manual_review_required
        parse_status = item.parse_status

        if expression_payload is None:
            confidence_value = ConfidenceLevel.needs_review
            parse_status = CriteriaParseStatus.needs_review
        else:
            try:
                validate_expression(expression_payload)
            except Exception:
                expression_payload = None
                confidence_value = ConfidenceLevel.needs_review
                manual_review_required = True
                parse_status = CriteriaParseStatus.needs_review
            else:
                if (
                    parse_status == CriteriaParseStatus.needs_review
                    and confidence_value == ConfidenceLevel.high
                    and not manual_review_required
                ):
                    parse_status = CriteriaParseStatus.parsed

        row = TrialCriteria(
            trial_id=trial_id,
            document_version=document_version,
            type=item.type,
            text=criterion_text,
            expression=expression_payload,
            confidence=confidence_value,
            manual_review_required=manual_review_required,
            source_order=item.source_order,
            section_label=item.section_label,
            parse_status=parse_status,
            approved_by=None,
            approved_at=None,
            rule_version=ENGINE_RULE_VERSION,
        )
        session.add(row)
        inserted_count += 1

    return inserted_count


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
            document_id_raw = payload.get("document_id")
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
            if not trial.document_title and metadata.document_title:
                trial.document_title = metadata.document_title
            if not trial.sponsor and metadata.sponsor:
                trial.sponsor = metadata.sponsor
            if not trial.phase and metadata.phase:
                trial.phase = metadata.phase

            document_version: int | None = None
            if document_id_raw:
                try:
                    document_id = UUID(document_id_raw)
                except ValueError:
                    logger.warning(
                        "Invalid trial document id in parse job payload",
                        extra={"job_id": str(job.id), "document_id": document_id_raw},
                    )
                else:
                    document_result = await session.execute(
                        select(TrialDocument).where(
                            TrialDocument.id == document_id,
                            TrialDocument.trial_id == trial.id,
                        )
                    )
                    trial_document = document_result.scalar_one_or_none()
                    if trial_document is not None:
                        document_version = trial_document.version

            if document_version is None:
                latest_doc_result = await session.execute(
                    select(TrialDocument)
                    .where(TrialDocument.trial_id == trial.id)
                    .order_by(TrialDocument.version.desc())
                )
                latest_doc = latest_doc_result.scalars().first()
                if latest_doc is not None:
                    document_version = latest_doc.version

            if document_version is None:
                logger.warning(
                    "Could not determine document version for criteria upsert",
                    extra={"trial_id": str(trial.id), "job_id": str(job.id)},
                )
            else:
                try:
                    await _upsert_parsed_criteria(
                        session=session,
                        trial_id=trial.id,
                        document_version=document_version,
                        text=text,
                    )
                except Exception:
                    logger.exception(
                        "Criteria parser failed during ingestion",
                        extra={"trial_id": str(trial.id), "document_version": document_version},
                    )

            if not trial.nct_id:
                title_candidates = _ordered_unique_titles(
                    [
                        trial.trial_title,
                        *metadata.title_candidates,
                    ]
                )[:CTG_TITLE_CANDIDATE_LIMIT]

                if title_candidates:
                    candidate_by_nct: dict[str, dict] = {}
                    search_failures = 0
                    total_title_searches = 0
                    searched_title_queries: set[str] = set()
                    indication_value = None
                    if trial.indication is not None:
                        indication_value = getattr(trial.indication, "value", str(trial.indication))

                    def _remember_candidate(
                        ctg_candidate: dict,
                        source: str,
                        reference_title: str | None,
                    ) -> None:
                        nct_id = (ctg_candidate.get("nctId") or "").upper().strip()
                        if not nct_id:
                            return

                        lexical_score = score_candidate(
                            trial_title=reference_title,
                            trial_phase=trial.phase,
                            trial_sponsor=trial.sponsor,
                            candidate_title=ctg_candidate.get("officialTitle"),
                            candidate_phase=ctg_candidate.get("phase"),
                            candidate_sponsor=ctg_candidate.get("sponsor"),
                        )
                        candidate_title = _candidate_title(ctg_candidate)
                        candidate_record = {
                            "nct_id": nct_id,
                            "title": candidate_title,
                            "phase": (ctg_candidate.get("phase") or None),
                            "sponsor": (ctg_candidate.get("sponsor") or None),
                            "source": source,
                            "url": f"https://clinicaltrials.gov/study/{nct_id}",
                            "lexical_score": _clamp_score(lexical_score),
                            "semantic_score": 0.0,
                            "final_score": _clamp_score(lexical_score),
                            "reason_codes": [],
                            "notes": "",
                        }
                        existing = candidate_by_nct.get(nct_id)
                        if existing is None:
                            candidate_by_nct[nct_id] = candidate_record
                            return

                        if not existing.get("title") and candidate_record.get("title"):
                            existing["title"] = candidate_record["title"]
                        if not existing.get("phase") and candidate_record.get("phase"):
                            existing["phase"] = candidate_record["phase"]
                        if not existing.get("sponsor") and candidate_record.get("sponsor"):
                            existing["sponsor"] = candidate_record["sponsor"]

                        existing_lexical = _clamp_score(existing.get("lexical_score"))
                        candidate_lexical = _clamp_score(candidate_record.get("lexical_score"))
                        is_better = candidate_lexical > existing_lexical
                        if abs(candidate_lexical - existing_lexical) < 1e-6:
                            is_better = CTG_SOURCE_PRIORITY.get(source, 0) > CTG_SOURCE_PRIORITY.get(
                                str(existing.get("source") or ""),
                                0,
                            )

                        if is_better:
                            existing["title"] = candidate_record["title"] or existing.get("title")
                            existing["phase"] = candidate_record["phase"] or existing.get("phase")
                            existing["sponsor"] = candidate_record["sponsor"] or existing.get("sponsor")
                            existing["source"] = source
                            existing["lexical_score"] = candidate_lexical
                            existing["final_score"] = candidate_lexical
                            existing["url"] = candidate_record["url"]

                    for candidate_title in title_candidates:
                        title_queries = [candidate_title, *generate_title_variants(candidate_title)]
                        for index, query in enumerate(title_queries):
                            query_key = _normalize_text(query)
                            if not query_key or query_key in searched_title_queries:
                                continue
                            searched_title_queries.add(query_key)
                            total_title_searches += 1

                            try:
                                ctg_candidates = await search_studies(query)
                            except Exception:
                                search_failures += 1
                                logger.exception(
                                    "CTG title search failed",
                                    extra={"trial_id": str(trial.id), "candidate_title": candidate_title, "query": query},
                                )
                                continue

                            source = CTG_SOURCE_TITLE if index == 0 else CTG_SOURCE_VARIANT
                            for ctg_candidate in ctg_candidates[:CTG_QUERY_RESULT_LIMIT]:
                                _remember_candidate(ctg_candidate, source, candidate_title)

                    keyword_queries = build_keyword_queries(
                        indication=indication_value,
                        phase=trial.phase,
                        sponsor=trial.sponsor,
                        trial_title=trial.trial_title or title_candidates[0],
                    )

                    for keyword_query in keyword_queries:
                        try:
                            ctg_candidates = await search_studies(keyword_query)
                        except Exception:
                            logger.exception(
                                "CTG keyword search failed",
                                extra={"trial_id": str(trial.id), "query": keyword_query},
                            )
                            continue

                        for ctg_candidate in ctg_candidates[:CTG_QUERY_RESULT_LIMIT]:
                            _remember_candidate(
                                ctg_candidate,
                                CTG_SOURCE_KEYWORD,
                                trial.trial_title or title_candidates[0],
                            )

                    seen_web_ncts: set[str] = set()
                    for candidate_title in title_candidates:
                        query = f"site:clinicaltrials.gov {candidate_title}"
                        try:
                            web_results = await search_web(query, max_results=CTG_WEB_RESULT_LIMIT)
                        except Exception:
                            logger.exception(
                                "CTG web fallback search failed",
                                extra={"trial_id": str(trial.id), "query": query},
                            )
                            continue

                        for result in web_results:
                            text_blob = " ".join(
                                filter(
                                    None,
                                    [
                                        str(result.get("url") or ""),
                                        str(result.get("title") or ""),
                                        str(result.get("snippet") or ""),
                                    ],
                                )
                            )
                            nct_id = extract_nct_from_text(text_blob)
                            if not nct_id or nct_id in seen_web_ncts:
                                continue
                            seen_web_ncts.add(nct_id)

                            try:
                                raw_study = await fetch_study(nct_id)
                            except Exception:
                                logger.exception(
                                    "CTG fetch failed for web fallback candidate",
                                    extra={"trial_id": str(trial.id), "nct_id": nct_id},
                                )
                                continue

                            fetched_candidate = first_study_result(raw_study)
                            if not fetched_candidate:
                                continue
                            fetched_candidate["nctId"] = nct_id
                            _remember_candidate(
                                fetched_candidate,
                                CTG_SOURCE_WEB,
                                trial.trial_title or candidate_title,
                            )

                    if candidate_by_nct:
                        protocol_context = build_protocol_summary_context(
                            trial_title=trial.trial_title or title_candidates[0],
                            document_title=trial.document_title or metadata.document_title,
                            indication=indication_value,
                            phase=trial.phase,
                            sponsor=trial.sponsor,
                            title_candidates=title_candidates,
                            protocol_text=text,
                        )

                        semantic_results = await asyncio.gather(
                            *[
                                score_candidate_semantic(
                                    protocol_context=protocol_context,
                                    trial_title=trial.trial_title or title_candidates[0],
                                    indication=indication_value,
                                    trial_phase=trial.phase,
                                    trial_sponsor=trial.sponsor,
                                    candidate=candidate_entry,
                                    lexical_score=_clamp_score(candidate_entry.get("lexical_score")),
                                )
                                for candidate_entry in candidate_by_nct.values()
                            ],
                            return_exceptions=True,
                        )

                        for candidate_entry, semantic_result in zip(candidate_by_nct.values(), semantic_results):
                            if isinstance(semantic_result, Exception):
                                logger.exception(
                                    "CTG semantic scoring failed",
                                    extra={"trial_id": str(trial.id), "nct_id": candidate_entry.get("nct_id")},
                                )
                                semantic_score = _clamp_score(candidate_entry.get("lexical_score"))
                                reason_codes: list[str] = []
                                notes = "Semantic scorer failed; using lexical fallback"
                            else:
                                semantic_score = _clamp_score(semantic_result.get("semantic_score"))
                                reason_codes = [str(code) for code in (semantic_result.get("reason_codes") or []) if str(code)]
                                notes = str(semantic_result.get("notes") or "").strip()

                            candidate_entry["semantic_score"] = semantic_score
                            candidate_entry["reason_codes"] = reason_codes
                            candidate_entry["notes"] = notes
                            candidate_entry["final_score"] = _blend_score(
                                _clamp_score(candidate_entry.get("lexical_score")),
                                semantic_score,
                            )

                        ranked_candidates = sorted(candidate_by_nct.values(), key=_candidate_sort_tuple, reverse=True)
                        best_candidate = ranked_candidates[0]
                        best_nct_id = str(best_candidate.get("nct_id") or "").strip()
                        best_source = str(best_candidate.get("source") or CTG_SOURCE_TITLE)
                        best_final_score = _clamp_score(best_candidate.get("final_score"))
                        best_core_signal_count = count_core_reason_codes(best_candidate.get("reason_codes") or [])

                        trial.ctg_candidate_pool = _build_candidate_pool(candidate_by_nct)
                        trial.ctg_match_confidence = best_final_score
                        if (
                            best_nct_id
                            and best_final_score >= CTG_AUTOFILL_FINAL_SCORE
                            and best_core_signal_count >= CTG_AUTO_ACCEPT_MIN_CORE_SIGNALS
                        ):
                            trial.nct_id = best_nct_id
                            trial.ctg_url = f"https://clinicaltrials.gov/study/{best_nct_id}"
                            _clear_ctg_candidate_fields(trial)
                            trial.ctg_match_note = (
                                f"{CTG_MATCH_NOTES_BY_SOURCE.get(best_source, CTG_MATCH_NOTES_BY_SOURCE[CTG_SOURCE_TITLE])}. "
                                f"Final score {best_final_score:.2f}."
                            )
                        else:
                            trial.nct_id = None
                            trial.ctg_url = None
                            trial.ctg_candidate_nct_id = best_nct_id or None
                            trial.ctg_candidate_url = (
                                f"https://clinicaltrials.gov/study/{best_nct_id}"
                                if best_nct_id
                                else None
                            )
                            trial.ctg_candidate_title = _candidate_title(best_candidate)
                            trial.ctg_candidate_source = best_source
                            trial.ctg_match_note = _manual_review_note(best_candidate)
                    elif total_title_searches and search_failures == total_title_searches:
                        trial.ctg_candidate_pool = None
                        trial.ctg_match_confidence = 0.0
                        _clear_ctg_candidate_fields(trial)
                        trial.ctg_match_note = "CTG title search failed"
                    else:
                        trial.ctg_candidate_pool = None
                        trial.ctg_match_confidence = 0.0
                        _clear_ctg_candidate_fields(trial)
                        trial.ctg_match_note = "No CTG match found from resolver ladder"
                else:
                    trial.ctg_candidate_pool = None
                    trial.ctg_match_confidence = 0.0
                    _clear_ctg_candidate_fields(trial)
                    trial.ctg_match_note = "No CTG match found from resolver ladder"
            else:
                trial.ctg_candidate_pool = None
                _clear_ctg_candidate_fields(trial)

            has_ctg_link = bool(trial.nct_id)
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
