from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from app.models.enums import Indication
from app.services.llm import chat_completion

METADATA_PROMPT = """Extract trial metadata from the protocol text.

Return only JSON object with keys:
- indication: one of ["aml","all","lymphoma","mm","transplant","gvhd"] or null
- nct_id: string like "NCT01234567" or null
- ctg_url: full ClinicalTrials.gov study URL or null
- trial_title: official CTG-style trial title (not protocol header label) or null
- document_title: protocol header/title page label (can differ from trial_title) or null
- sponsor: sponsor name or null
- phase: phase text like "Phase 1", "Phase 2/3" or null

Never guess values that are not explicitly in the text."""

TITLE_SCAN_LINE_LIMIT = 120
MAX_TITLE_CANDIDATES = 12
MIN_TITLE_LENGTH = 25

NCT_ID_PATTERN = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
PHASE_PATTERN = re.compile(r"\bphase\s*([0-4ivx]+(?:/[0-4ivx]+)?[a-z]?)\b", re.IGNORECASE)
SPONSOR_PATTERN = re.compile(
    r"(?:lead\s+sponsor|study\s+sponsor|sponsored\s+by|sponsor|funded\s+by)\s*[:\-]?\s*([^\n\r]{2,180})",
    re.IGNORECASE,
)
TITLE_HINT_PATTERN = re.compile(
    r"(?im)^(?=.{25,500}$).*(?:\bA\s+Phase\b|\b(?:acute myeloid leukemia|acute lymphoblastic leukemia|lymphoma|multiple myeloma|gvhd|graft[-\s]versus[-\s]host disease|transplant)\b.*\b(?:study|trial)\b).*$"
)
DRUG_LIKE_PATTERN = re.compile(
    r"\b(?:[A-Za-z]{2,}-\d{2,4}|[A-Z]{2,}\d{1,4}|[A-Za-z]{4,}(?:mab|nib))\b"
)
DISEASE_PATTERN = re.compile(
    r"\b(?:leukemia|lymphoma|myeloma|tumou?r|cancer|carcinoma|graft[\s-]?versus[\s-]?host|gvhd|transplant|relapse|refractory)\b",
    re.IGNORECASE,
)

CTG_SIGNAL_TERMS = (
    "study of",
    "in patients with",
    "randomized",
    "open-label",
    "multicenter",
    "double-blind",
)
BOILERPLATE_TERMS = (
    "protocol",
    "synopsis",
    "version",
    "confidential",
    "table of contents",
    "investigator brochure",
    "amendment",
)
DRUG_CONTENT_TERMS = (
    "agent",
    "therapy",
    "inhibitor",
    "antibody",
    "car-t",
    "cell therapy",
)
HEADER_SIGNAL_TERMS = (
    "protocol",
    "synopsis",
    "investigator brochure",
    "amendment",
    "version",
)
GENERIC_TITLE_HEADINGS = {
    "protocol",
    "study protocol",
    "clinical protocol",
    "protocol synopsis",
    "synopsis",
    "table of contents",
    "confidential",
    "investigator brochure",
}

INDICATION_KEYWORDS: dict[Indication, tuple[str, ...]] = {
    Indication.aml: ("acute myeloid leukemia", " aml "),
    Indication.all: ("acute lymphoblastic leukemia", " all "),
    Indication.lymphoma: ("lymphoma",),
    Indication.mm: ("multiple myeloma", " myeloma "),
    Indication.transplant: ("transplant", "hsct", "hematopoietic stem cell"),
    Indication.gvhd: ("graft-versus-host disease", "graft versus host disease", " gvhd "),
}


@dataclass
class TrialMetadataExtraction:
    indication: Indication | None = None
    nct_id: str | None = None
    ctg_url: str | None = None
    trial_title: str | None = None
    document_title: str | None = None
    sponsor: str | None = None
    phase: str | None = None
    title_candidates: list[str] = field(default_factory=list)

    @property
    def has_core_fields(self) -> bool:
        return bool(self.indication and self.nct_id and self.sponsor and self.phase)


def _clean_json_block(raw: str) -> str:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def _parse_indication(value: str | None) -> Indication | None:
    if not value:
        return None
    normalized = value.strip().lower()
    try:
        return Indication(normalized)
    except ValueError:
        return None


def _normalize_nct_id(value: str | None) -> str | None:
    if not value:
        return None
    match = NCT_ID_PATTERN.search(str(value).upper())
    return match.group(0).upper() if match else None


def _phase_label(value: str | None) -> str | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    if stripped.lower().startswith("phase"):
        return stripped
    return f"Phase {stripped}"


def _build_ctg_url(nct_id: str | None) -> str | None:
    if not nct_id:
        return None
    return f"https://clinicaltrials.gov/study/{nct_id}"


def _normalize_title_candidate(value: str) -> str | None:
    cleaned = re.sub(r"\s+", " ", value).strip(" -:\t\r\n")
    if not cleaned:
        return None
    return cleaned[:500]


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    return any(term in value for term in terms)


def _looks_generic_heading(value: str) -> bool:
    lowered = value.lower().strip()
    compact = re.sub(r"[^a-z0-9 ]", "", lowered)
    if compact in GENERIC_TITLE_HEADINGS:
        return True
    return compact.startswith("version ") or compact.startswith("page ")


def _is_boilerplate_title(value: str | None) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if _looks_generic_heading(value):
        return True
    if not _contains_any(lowered, BOILERPLATE_TERMS):
        return False
    has_study_signals = _contains_any(lowered, CTG_SIGNAL_TERMS) or lowered.startswith("a phase")
    return not has_study_signals


def _ctg_title_score(value: str) -> float:
    lowered = value.lower()
    score = 0.0

    if lowered.startswith("a phase"):
        score += 5.0
    if "study of" in lowered:
        score += 2.0
    if "in patients with" in lowered:
        score += 2.0
    if _contains_any(lowered, CTG_SIGNAL_TERMS):
        score += 1.5
    if DISEASE_PATTERN.search(value):
        score += 1.8
    if DRUG_LIKE_PATTERN.search(value) or _contains_any(lowered, DRUG_CONTENT_TERMS):
        score += 1.2

    if len(value) < MIN_TITLE_LENGTH:
        score -= 3.0
    elif len(value) < 40:
        score -= 0.7
    elif 55 <= len(value) <= 320:
        score += 0.8

    if _is_boilerplate_title(value):
        score -= 4.0
    else:
        for term in BOILERPLATE_TERMS:
            if term in lowered:
                score -= 2.0

    return score


def _document_header_score(value: str, line_number: int) -> float:
    lowered = value.lower()
    score = 0.0

    if line_number < 5:
        score += 2.0
    elif line_number < 20:
        score += 1.0

    if _contains_any(lowered, HEADER_SIGNAL_TERMS):
        score += 2.4
    if ":" in value:
        score += 0.6
    if len(value) < 12:
        score -= 1.2
    elif 16 <= len(value) <= 220:
        score += 0.4
    if len(value) > 320:
        score -= 1.0

    return score


def _rank_title_candidates(candidates: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = _normalize_title_candidate(candidate)
        if normalized is None:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)

    scored = [(candidate, _ctg_title_score(candidate), idx) for idx, candidate in enumerate(deduped)]
    scored.sort(key=lambda item: (-item[1], item[2]))
    return [candidate for candidate, _, _ in scored[:MAX_TITLE_CANDIDATES]]


def extract_title_candidates(text: str) -> list[str]:
    lines = text.splitlines()[:TITLE_SCAN_LINE_LIMIT]
    candidates: list[str] = []

    for line_index, line in enumerate(lines):
        candidate = _normalize_title_candidate(line)
        if candidate is None:
            continue
        candidates.append(candidate)

        if ":" in candidate:
            prefix, suffix = candidate.split(":", 1)
            if len(prefix) <= 32:
                normalized_suffix = _normalize_title_candidate(suffix)
                if normalized_suffix is not None:
                    candidates.append(normalized_suffix)

        if line_index + 1 < len(lines):
            next_candidate = _normalize_title_candidate(lines[line_index + 1])
            if next_candidate and len(candidate) <= 220 and len(next_candidate) <= 220:
                combined = _normalize_title_candidate(f"{candidate} {next_candidate}")
                if combined and len(combined) >= MIN_TITLE_LENGTH:
                    candidates.append(combined)

    ranked = _rank_title_candidates(candidates)
    if ranked:
        return ranked

    match = TITLE_HINT_PATTERN.search(text)
    if match:
        hint_title = _normalize_title_candidate(match.group(0))
        if hint_title:
            return [hint_title]
    return []


def _extract_document_title(text: str, title_candidates: list[str]) -> str | None:
    lines = text.splitlines()[:TITLE_SCAN_LINE_LIMIT]
    best_title: str | None = None
    best_score = float("-inf")

    for idx, line in enumerate(lines):
        candidate = _normalize_title_candidate(line)
        if candidate is None:
            continue
        score = _document_header_score(candidate, idx)
        if score > best_score:
            best_score = score
            best_title = candidate

    if best_title:
        return best_title
    return title_candidates[0] if title_candidates else None


def _select_trial_title(llm_title: str | None, heuristic_title: str | None) -> str | None:
    llm_normalized = _normalize_title_candidate(llm_title) if llm_title else None
    heuristic_normalized = _normalize_title_candidate(heuristic_title) if heuristic_title else None

    if llm_normalized is None:
        return heuristic_normalized
    if heuristic_normalized is None:
        return llm_normalized

    llm_score = _ctg_title_score(llm_normalized)
    heuristic_score = _ctg_title_score(heuristic_normalized)

    if _is_boilerplate_title(llm_normalized) and heuristic_score >= llm_score:
        return heuristic_normalized
    if heuristic_score >= llm_score + 0.75:
        return heuristic_normalized
    return llm_normalized


def _extract_fallback_metadata(text: str) -> TrialMetadataExtraction:
    haystack = f" {text.lower()} "
    indication = None
    for candidate, keywords in INDICATION_KEYWORDS.items():
        if any(keyword in haystack for keyword in keywords):
            indication = candidate
            break

    nct_match = NCT_ID_PATTERN.search(text)
    nct_id = nct_match.group(0).upper() if nct_match else None

    phase_match = PHASE_PATTERN.search(text)
    phase = _phase_label(phase_match.group(1).upper() if phase_match else None)

    sponsor_match = SPONSOR_PATTERN.search(text)
    sponsor = sponsor_match.group(1).strip(" .;:-") if sponsor_match else None

    title_candidates = extract_title_candidates(text)
    trial_title = title_candidates[0] if title_candidates else None
    document_title = _extract_document_title(text, title_candidates)

    return TrialMetadataExtraction(
        indication=indication,
        nct_id=nct_id,
        ctg_url=_build_ctg_url(nct_id),
        trial_title=trial_title,
        document_title=document_title,
        sponsor=sponsor,
        phase=phase,
        title_candidates=title_candidates,
    )


def _merge_metadata(primary: TrialMetadataExtraction, fallback: TrialMetadataExtraction) -> TrialMetadataExtraction:
    nct_id = primary.nct_id or fallback.nct_id
    ctg_url = primary.ctg_url or fallback.ctg_url or _build_ctg_url(nct_id)
    trial_title = _select_trial_title(primary.trial_title, fallback.trial_title)
    document_title = _normalize_title_candidate(primary.document_title or fallback.document_title or "")
    if document_title is None:
        document_title = None

    merged_candidates = _rank_title_candidates(
        [title for title in [trial_title, primary.trial_title, fallback.trial_title, *fallback.title_candidates] if title]
    )

    return TrialMetadataExtraction(
        indication=primary.indication or fallback.indication,
        nct_id=nct_id,
        ctg_url=ctg_url,
        trial_title=trial_title,
        document_title=document_title,
        sponsor=primary.sponsor or fallback.sponsor,
        phase=primary.phase or fallback.phase,
        title_candidates=merged_candidates,
    )


async def extract_trial_metadata_from_text(text: str) -> TrialMetadataExtraction:
    fallback = _extract_fallback_metadata(text)
    llm_output = await chat_completion(
        messages=[{"role": "user", "content": f"Protocol text:\n\n{text[:18000]}"}],
        system=METADATA_PROMPT,
        max_tokens=512,
    )
    if llm_output is None:
        return fallback

    try:
        payload = json.loads(_clean_json_block(llm_output))
        if not isinstance(payload, dict):
            return fallback
    except json.JSONDecodeError:
        return fallback

    llm_metadata = TrialMetadataExtraction(
        indication=_parse_indication(payload.get("indication")),
        nct_id=_normalize_nct_id(payload.get("nct_id")),
        ctg_url=(payload.get("ctg_url") or None),
        trial_title=(str(payload.get("trial_title")).strip() if payload.get("trial_title") else None),
        document_title=(str(payload.get("document_title")).strip() if payload.get("document_title") else None),
        sponsor=(str(payload.get("sponsor")).strip() if payload.get("sponsor") else None),
        phase=_phase_label(str(payload.get("phase")).strip() if payload.get("phase") else None),
    )
    return _merge_metadata(llm_metadata, fallback)
