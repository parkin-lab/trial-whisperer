from __future__ import annotations

import json
import re
from dataclasses import dataclass

from app.models.enums import Indication
from app.services.llm import chat_completion

METADATA_PROMPT = """Extract trial metadata from the protocol text.

Return only JSON object with keys:
- indication: one of ["aml","all","lymphoma","mm","transplant","gvhd"] or null
- nct_id: string like "NCT01234567" or null
- ctg_url: full ClinicalTrials.gov study URL or null
- trial_title: official or brief study title from the protocol text or null
- sponsor: sponsor name or null
- phase: phase text like "Phase 1", "Phase 2/3" or null

Never guess values that are not explicitly in the text."""

NCT_ID_PATTERN = re.compile(r"\bNCT\d{8}\b", re.IGNORECASE)
PHASE_PATTERN = re.compile(r"\bphase\s*([0-4ivx]+(?:/[0-4ivx]+)?[a-z]?)\b", re.IGNORECASE)
SPONSOR_PATTERN = re.compile(
    r"(?:lead\s+sponsor|study\s+sponsor|sponsored\s+by|sponsor|funded\s+by)\s*[:\-]?\s*([^\n\r]{2,180})",
    re.IGNORECASE,
)
TITLE_HINT_PATTERN = re.compile(
    r"(?im)^(?=.{25,500}$).*(?:\bA\s+Phase\b|\b(?:acute myeloid leukemia|acute lymphoblastic leukemia|lymphoma|multiple myeloma|gvhd|graft[-\s]versus[-\s]host disease|transplant)\b.*\b(?:study|trial)\b).*$"
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
    sponsor: str | None = None
    phase: str | None = None

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


def _looks_generic_heading(value: str) -> bool:
    lowered = value.lower().strip()
    compact = re.sub(r"[^a-z0-9 ]", "", lowered)
    if compact in GENERIC_TITLE_HEADINGS:
        return True
    return compact.startswith("version ") or compact.startswith("page ")


def _extract_fallback_title(text: str) -> str | None:
    lines = [line.strip() for line in text.splitlines()]

    for line in lines:
        candidate = _normalize_title_candidate(line)
        if candidate is None or len(candidate) < 25:
            continue
        if _looks_generic_heading(candidate):
            continue
        return candidate

    match = TITLE_HINT_PATTERN.search(text)
    if match:
        return _normalize_title_candidate(match.group(0))
    return None


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
    trial_title = _extract_fallback_title(text)

    return TrialMetadataExtraction(
        indication=indication,
        nct_id=nct_id,
        ctg_url=_build_ctg_url(nct_id),
        trial_title=trial_title,
        sponsor=sponsor,
        phase=phase,
    )


def _merge_metadata(primary: TrialMetadataExtraction, fallback: TrialMetadataExtraction) -> TrialMetadataExtraction:
    nct_id = primary.nct_id or fallback.nct_id
    ctg_url = primary.ctg_url or fallback.ctg_url or _build_ctg_url(nct_id)
    return TrialMetadataExtraction(
        indication=primary.indication or fallback.indication,
        nct_id=nct_id,
        ctg_url=ctg_url,
        trial_title=primary.trial_title or fallback.trial_title,
        sponsor=primary.sponsor or fallback.sponsor,
        phase=primary.phase or fallback.phase,
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
        sponsor=(str(payload.get("sponsor")).strip() if payload.get("sponsor") else None),
        phase=_phase_label(str(payload.get("phase")).strip() if payload.get("phase") else None),
    )
    return _merge_metadata(llm_metadata, fallback)
