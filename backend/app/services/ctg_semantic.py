from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.models.enums import Indication
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

_ALLOWED_REASON_CODES = {
    "disease_match",
    "phase_match",
    "intervention_match",
    "population_match",
    "sponsor_match",
}
_CORE_REASON_CODES = {"disease_match", "intervention_match", "phase_match"}

INDICATION_KEYWORDS: dict[str, tuple[str, ...]] = {
    Indication.aml.value: ("acute myeloid leukemia", " aml", "myeloid leukemia"),
    Indication.all.value: ("acute lymphoblastic leukemia", " all", "lymphoblastic leukemia"),
    Indication.lymphoma.value: ("lymphoma",),
    Indication.mm.value: ("multiple myeloma", " myeloma"),
    Indication.transplant.value: ("transplant", "hsct", "stem cell transplant"),
    Indication.gvhd.value: ("graft-versus-host", "graft versus host", " gvhd"),
}

SEMANTIC_SCORE_SYSTEM_PROMPT = """You are a clinical trial matching scorer.

Given protocol context and one ClinicalTrials.gov candidate, return only JSON:
{
  "nct_id": "NCT...",
  "semantic_score": 0.0,
  "reason_codes": ["disease_match","phase_match"],
  "notes": "short rationale"
}

Rules:
- semantic_score must be a float between 0 and 1.
- reason_codes can include only: disease_match, phase_match, intervention_match, population_match, sponsor_match.
- Keep notes under 160 characters.
- Do not use markdown.
- Never include keys other than nct_id, semantic_score, reason_codes, notes.
"""


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    lowered = value.lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def _tokenize(value: str | None) -> set[str]:
    return {token for token in _normalize_text(value).split(" ") if len(token) >= 3}


def _strip_code_fence(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def _extract_json_dict(raw: str) -> dict[str, Any] | None:
    cleaned = _strip_code_fence(raw)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _extract_protocol_snippets(protocol_text: str | None, limit: int = 6) -> list[str]:
    if not protocol_text:
        return []

    lines = []
    for raw_line in protocol_text.splitlines():
        line = re.sub(r"\s+", " ", raw_line).strip()
        if len(line) < 40 or len(line) > 320:
            continue
        if line.lower().startswith(("page ", "table ", "figure ")):
            continue
        lines.append(line)

    ranked: list[tuple[float, str]] = []
    for line in lines:
        lowered = line.lower()
        score = 0.0
        if "phase" in lowered:
            score += 2.0
        if "sponsor" in lowered or "funded" in lowered:
            score += 1.2
        if "study" in lowered or "trial" in lowered:
            score += 0.8
        if "patients" in lowered or "participant" in lowered:
            score += 1.0
        if re.search(r"\b(leukemia|lymphoma|myeloma|gvhd|transplant|refractory|relapsed)\b", lowered):
            score += 1.2
        if re.search(r"\b([a-z]{2,}-\d{2,4}|car-t|cell therapy|inhibitor|antibody)\b", lowered):
            score += 1.2
        ranked.append((score, line))

    ranked.sort(key=lambda item: item[0], reverse=True)
    snippets: list[str] = []
    seen: set[str] = set()
    for _, line in ranked:
        key = _normalize_text(line)
        if not key or key in seen:
            continue
        seen.add(key)
        snippets.append(line)
        if len(snippets) >= limit:
            break

    if not snippets:
        paragraphs = re.split(r"\n\s*\n", protocol_text)
        for paragraph in paragraphs:
            candidate = re.sub(r"\s+", " ", paragraph).strip()
            if len(candidate) >= 40:
                snippets.append(candidate[:280])
            if len(snippets) >= min(limit, 3):
                break

    return snippets


def build_protocol_summary_context(
    *,
    trial_title: str | None,
    document_title: str | None,
    indication: str | None,
    phase: str | None,
    sponsor: str | None,
    title_candidates: list[str] | None,
    protocol_text: str | None,
) -> str:
    lines: list[str] = [
        f"Trial title: {trial_title or 'unknown'}",
        f"Document title: {document_title or 'unknown'}",
        f"Indication: {indication or 'unknown'}",
        f"Phase: {phase or 'unknown'}",
        f"Sponsor: {sponsor or 'unknown'}",
    ]

    variants = [title.strip() for title in (title_candidates or []) if title and title.strip()]
    if variants:
        lines.append("Title variants: " + " | ".join(variants[:4]))

    snippets = _extract_protocol_snippets(protocol_text)
    if snippets:
        lines.append("Protocol snippets:")
        for index, snippet in enumerate(snippets, start=1):
            lines.append(f"{index}. {snippet[:280]}")

    payload = "\n".join(lines)
    return payload[:4500]


def _heuristic_reason_codes(
    *,
    trial_title: str | None,
    indication: str | None,
    trial_phase: str | None,
    trial_sponsor: str | None,
    protocol_context: str,
    candidate_title: str | None,
    candidate_phase: str | None,
    candidate_sponsor: str | None,
) -> list[str]:
    reason_codes: list[str] = []

    trial_phase_norm = _normalize_text(trial_phase)
    candidate_phase_norm = _normalize_text(candidate_phase)
    if trial_phase_norm and candidate_phase_norm and (
        trial_phase_norm in candidate_phase_norm or candidate_phase_norm in trial_phase_norm
    ):
        reason_codes.append("phase_match")

    trial_sponsor_tokens = _tokenize(trial_sponsor)
    candidate_sponsor_tokens = _tokenize(candidate_sponsor)
    if trial_sponsor_tokens and candidate_sponsor_tokens and (trial_sponsor_tokens & candidate_sponsor_tokens):
        reason_codes.append("sponsor_match")

    trial_title_tokens = _tokenize(trial_title)
    candidate_title_tokens = _tokenize(candidate_title)
    shared_tokens = trial_title_tokens & candidate_title_tokens
    if shared_tokens and len(shared_tokens) >= 2:
        reason_codes.append("intervention_match")

    indication_norm = _normalize_text(indication)
    candidate_title_norm = _normalize_text(candidate_title)
    context_norm = _normalize_text(protocol_context)
    indication_terms = INDICATION_KEYWORDS.get(indication_norm, ())
    if any(term.strip() and term.strip() in f" {candidate_title_norm} " for term in indication_terms):
        reason_codes.append("disease_match")
    elif indication_terms and any(term.strip() and term.strip() in f" {context_norm} " for term in indication_terms):
        if any(term.strip() and term.strip() in f" {candidate_title_norm} " for term in indication_terms[:1]):
            reason_codes.append("disease_match")

    if (
        "patients" in candidate_title_norm
        and ("participants" in context_norm or "patients" in context_norm or "eligible" in context_norm)
    ):
        reason_codes.append("population_match")

    deduped: list[str] = []
    for code in reason_codes:
        if code in _ALLOWED_REASON_CODES and code not in deduped:
            deduped.append(code)
    return deduped


def _clamp_score(value: Any, fallback: float = 0.0) -> float:
    try:
        score = float(value)
    except (TypeError, ValueError):
        score = fallback
    return max(0.0, min(1.0, score))


async def score_candidate_semantic(
    *,
    protocol_context: str,
    trial_title: str | None,
    indication: str | None,
    trial_phase: str | None,
    trial_sponsor: str | None,
    candidate: dict[str, Any],
    lexical_score: float,
) -> dict[str, Any]:
    nct_id = str(candidate.get("nct_id") or "").upper().strip()
    candidate_title = candidate.get("title")
    candidate_phase = candidate.get("phase")
    candidate_sponsor = candidate.get("sponsor")

    fallback_reasons = _heuristic_reason_codes(
        trial_title=trial_title,
        indication=indication,
        trial_phase=trial_phase,
        trial_sponsor=trial_sponsor,
        protocol_context=protocol_context,
        candidate_title=candidate_title,
        candidate_phase=candidate_phase,
        candidate_sponsor=candidate_sponsor,
    )

    fallback = {
        "nct_id": nct_id,
        "semantic_score": _clamp_score(lexical_score),
        "reason_codes": fallback_reasons,
        "notes": "Heuristic semantic fallback (LLM unavailable or invalid response)",
    }

    if not nct_id:
        return fallback

    user_payload = {
        "protocol_context": protocol_context,
        "candidate": {
            "nct_id": nct_id,
            "title": candidate_title,
            "phase": candidate_phase,
            "sponsor": candidate_sponsor,
            "source": candidate.get("source"),
            "url": candidate.get("url"),
        },
    }

    response = await chat_completion(
        messages=[{"role": "user", "content": json.dumps(user_payload, ensure_ascii=True)}],
        system=SEMANTIC_SCORE_SYSTEM_PROMPT,
        max_tokens=300,
    )
    if response is None:
        return fallback

    parsed = _extract_json_dict(response)
    if not parsed:
        logger.warning("Semantic CTG scorer returned non-JSON payload")
        return fallback

    reason_codes_raw = parsed.get("reason_codes")
    reason_codes: list[str] = []
    if isinstance(reason_codes_raw, list):
        for code in reason_codes_raw:
            code_text = str(code).strip()
            if code_text in _ALLOWED_REASON_CODES and code_text not in reason_codes:
                reason_codes.append(code_text)

    notes = str(parsed.get("notes") or "").strip()[:160] or "Semantic scorer matched candidate"

    return {
        "nct_id": nct_id,
        "semantic_score": _clamp_score(parsed.get("semantic_score"), fallback=_clamp_score(lexical_score)),
        "reason_codes": reason_codes,
        "notes": notes,
    }


def count_core_reason_codes(reason_codes: list[str] | None) -> int:
    if not reason_codes:
        return 0
    return sum(1 for code in reason_codes if code in _CORE_REASON_CODES)
