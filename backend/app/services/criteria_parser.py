"""
Protocol criteria parser.

Pipeline:
1) Deterministically split protocol text into row-level IC/EC criteria.
2) Optionally ask the LLM for structured expression mappings per row.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Literal

from app.engine.schema import validate_expression
from app.models.enums import ConfidenceLevel, CriteriaParseStatus, CriteriaType
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

MAPPING_SYSTEM_PROMPT = """You are a clinical trial criteria mapper.

Given row-level eligibility criteria, return JSON array entries with:
- source_order: integer from input
- expression: structured rule or null
- confidence: "high" or "needs_review"
- manual_review_required: boolean

Expression schema:
{"op": "gte"|"lte"|"gt"|"lt"|"eq"|"neq", "field": str, "value": number|str|bool, "unit": str|null}
{"op": "is_true"|"is_false", "field": str}
{"op": "in"|"not_in", "field": str, "values": []}
{"op": "within_days", "field": str, "days": int}
{"op": "and"|"or", "operands": [...]}
{"op": "not", "operands": [single_expr]}

Rules:
- Never invent values.
- If uncertain/ambiguous, set expression=null and confidence="needs_review".
- Output JSON only. No markdown.
"""

AI_EXTRACTION_SYSTEM_PROMPT = """You extract inclusion and exclusion criteria from a protocol.

Return JSON array only. Each item must be:
{
  "type": "inclusion" | "exclusion",
  "text": "single criterion text",
  "quote": "short direct quote snippet from the protocol supporting this criterion, or null",
  "confidence": "high" | "needs_review"
}

Rules:
- Use only criteria explicitly written in the protocol text.
- Do not infer, generalize, or invent criteria.
- Keep each output item atomic (one condition per row when possible).
- If uncertain, set confidence to "needs_review".
- Include direct quote snippets when available.
- Output JSON only (no markdown, no prose).
"""

SECTION_LABELS = {
    CriteriaType.inclusion: "Inclusion",
    CriteriaType.exclusion: "Exclusion",
}

AI_SECTION_LABELS = {
    CriteriaType.inclusion: "AI Inclusion",
    CriteriaType.exclusion: "AI Exclusion",
}

EXCLUSION_HEADING_RE = re.compile(r"\bexclusion(?:\s+criteria)?\b", re.IGNORECASE)
INCLUSION_HEADING_RE = re.compile(r"\binclusion(?:\s+criteria)?\b|\beligibility\s+criteria\b", re.IGNORECASE)
EXPLICIT_CRITERIA_HEADING_RE = re.compile(
    r"^\s*(?:\d+(?:\.\d+)*\s*[-.)]?\s*)?(eligibility|inclusion|exclusion)\s+criteria\s*:?\s*$",
    re.IGNORECASE,
)
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•●▪‣]\s+|\(?\d+[.)]\s+|\(?[a-zA-Z][.)]\s+)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9(])")
GENERIC_HEADING_CANDIDATE_RE = re.compile(r"^\s*(?:\d+(?:\.\d+)*\s*[-.)]?\s*)?[A-Za-z][A-Za-z0-9 ,()/:-]{1,100}$")


@dataclass
class ParsedCriterion:
    type: CriteriaType
    text: str
    expression: dict | None
    confidence: ConfidenceLevel
    manual_review_required: bool
    source_order: int | None = None
    section_label: str | None = None
    parse_status: CriteriaParseStatus = CriteriaParseStatus.needs_review
    quote_snippet: str | None = None
    from_fallback: bool = False


def _strip_code_fence(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _heading_kind(line: str) -> Literal["eligibility", "inclusion", "exclusion"] | None:
    match = EXPLICIT_CRITERIA_HEADING_RE.match(line.strip())
    if not match:
        return None
    return str(match.group(1)).lower()  # type: ignore[return-value]


def _looks_like_other_heading(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    if BULLET_PREFIX_RE.match(stripped):
        return False
    if not GENERIC_HEADING_CANDIDATE_RE.match(stripped):
        return False
    if stripped.endswith((".", ";", "!", "?")):
        return False

    words = [word for word in re.split(r"\s+", stripped.rstrip(":")) if word]
    if len(words) > 12:
        return False

    letters = [ch for ch in stripped if ch.isalpha()]
    if not letters:
        return False
    uppercase_ratio = sum(1 for ch in letters if ch.isupper()) / len(letters)
    title_case_ratio = sum(1 for word in words if word[:1].isupper()) / max(len(words), 1)
    return uppercase_ratio >= 0.75 or title_case_ratio >= 0.85


def _detect_section_heading(line: str) -> tuple[CriteriaType | None, str | None]:
    normalized = line.strip()
    if not normalized:
        return None, None

    has_inclusion = bool(INCLUSION_HEADING_RE.search(normalized))
    has_exclusion = bool(EXCLUSION_HEADING_RE.search(normalized))
    if has_inclusion and not has_exclusion:
        return CriteriaType.inclusion, SECTION_LABELS[CriteriaType.inclusion]
    if has_exclusion and not has_inclusion:
        return CriteriaType.exclusion, SECTION_LABELS[CriteriaType.exclusion]
    return None, None


def _split_sentence_candidates(value: str) -> list[str]:
    text = _normalize_text(value)
    if not text:
        return []
    pieces = [piece.strip() for piece in SENTENCE_SPLIT_RE.split(text) if piece.strip()]
    return pieces if pieces else [text]


def _extract_rows_from_section(
    *,
    section_lines: list[str],
    section_type: CriteriaType,
    section_label: str,
    source_order_start: int,
) -> tuple[list[ParsedCriterion], int]:
    rows: list[ParsedCriterion] = []
    source_order = source_order_start
    has_marked_list = any(BULLET_PREFIX_RE.match(line) for line in section_lines if line.strip())

    pending_item: str | None = None
    pending_paragraph: str | None = None

    def _append_segments(raw_value: str) -> None:
        nonlocal source_order
        for segment in _split_sentence_candidates(raw_value):
            if len(segment) < 3:
                continue
            rows.append(
                ParsedCriterion(
                    type=section_type,
                    text=segment,
                    expression=None,
                    confidence=ConfidenceLevel.needs_review,
                    manual_review_required=True,
                    source_order=source_order,
                    section_label=section_label,
                    parse_status=CriteriaParseStatus.needs_review,
                )
            )
            source_order += 1

    def _flush_item() -> None:
        nonlocal pending_item
        if pending_item:
            _append_segments(pending_item)
            pending_item = None

    def _flush_paragraph() -> None:
        nonlocal pending_paragraph
        if pending_paragraph:
            _append_segments(pending_paragraph)
            pending_paragraph = None

    for raw_line in section_lines:
        stripped = raw_line.strip()
        if not stripped:
            _flush_item()
            _flush_paragraph()
            continue

        marker_match = BULLET_PREFIX_RE.match(raw_line)
        if marker_match:
            _flush_item()
            _flush_paragraph()
            pending_item = raw_line[marker_match.end():].strip() or None
            continue

        if has_marked_list:
            if pending_item is None:
                # Ignore narrative prose around bulleted blocks.
                continue
            pending_item = _normalize_text(f"{pending_item} {stripped}")
            if stripped.endswith((".", ";", "!", "?")):
                _flush_item()
            continue

        pending_paragraph = _normalize_text(f"{pending_paragraph} {stripped}") if pending_paragraph else stripped
        if stripped.endswith((".", ";", "!", "?")):
            _flush_paragraph()

    _flush_item()
    _flush_paragraph()
    return rows, source_order


def _extract_row_level_criteria_from_headings(text: str) -> list[ParsedCriterion]:
    lines = text.splitlines()
    headings: list[tuple[int, Literal["eligibility", "inclusion", "exclusion"]]] = []
    for idx, line in enumerate(lines):
        heading_kind = _heading_kind(line)
        if heading_kind:
            headings.append((idx, heading_kind))

    if not headings:
        return []

    rows: list[ParsedCriterion] = []
    source_order = 1

    for heading_idx, heading_kind in headings:
        section_type = CriteriaType.exclusion if heading_kind == "exclusion" else CriteriaType.inclusion
        section_label = "Eligibility" if heading_kind == "eligibility" else SECTION_LABELS[section_type]

        section_end = len(lines)
        for idx in range(heading_idx + 1, len(lines)):
            candidate = lines[idx]
            if _heading_kind(candidate):
                section_end = idx
                break
            if _looks_like_other_heading(candidate):
                section_end = idx
                break

        section_rows, source_order = _extract_rows_from_section(
            section_lines=lines[heading_idx + 1 : section_end],
            section_type=section_type,
            section_label=section_label,
            source_order_start=source_order,
        )
        rows.extend(section_rows)

    return rows


def _extract_row_level_criteria_fallback(text: str) -> list[ParsedCriterion]:
    rows: list[ParsedCriterion] = []
    current_type: CriteriaType | None = None
    current_label: str | None = None
    pending_paragraph: str | None = None
    source_order = 1

    def _append_segments(raw_value: str) -> None:
        nonlocal source_order
        for segment in _split_sentence_candidates(raw_value):
            rows.append(
                ParsedCriterion(
                    type=current_type or CriteriaType.inclusion,
                    text=segment,
                    expression=None,
                    confidence=ConfidenceLevel.needs_review,
                    manual_review_required=True,
                    source_order=source_order,
                    section_label=current_label,
                    parse_status=CriteriaParseStatus.needs_review,
                    from_fallback=True,
                )
            )
            source_order += 1

    def _flush_pending() -> None:
        nonlocal pending_paragraph
        if pending_paragraph:
            _append_segments(pending_paragraph)
            pending_paragraph = None

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped:
            _flush_pending()
            continue

        heading_type, heading_label = _detect_section_heading(stripped)
        if heading_type is not None:
            _flush_pending()
            current_type = heading_type
            current_label = heading_label
            continue

        if current_type is None:
            continue

        marker_match = BULLET_PREFIX_RE.match(raw_line)
        if marker_match:
            _flush_pending()
            criterion_text = raw_line[marker_match.end():].strip()
            if criterion_text:
                _append_segments(criterion_text)
            continue

        if pending_paragraph:
            pending_paragraph = f"{pending_paragraph} {stripped}"
        else:
            pending_paragraph = stripped

        if stripped.endswith((".", ";", "!", "?")):
            _flush_pending()

    _flush_pending()
    return rows


def _extract_row_level_criteria(text: str) -> list[ParsedCriterion]:
    has_explicit_headings = any(_heading_kind(line) for line in text.splitlines())
    if has_explicit_headings:
        return _extract_row_level_criteria_from_headings(text)

    fallback_rows = _extract_row_level_criteria_fallback(text)
    for row in fallback_rows:
        row.parse_status = CriteriaParseStatus.needs_review
        row.confidence = ConfidenceLevel.needs_review
        row.manual_review_required = True
    return fallback_rows


async def _map_structured_expressions(criteria: list[ParsedCriterion]) -> dict[int, dict]:
    if not criteria:
        return {}

    mapping_payload = [
        {"source_order": item.source_order, "type": item.type.value, "text": item.text}
        for item in criteria
    ]
    response = await chat_completion(
        messages=[{"role": "user", "content": json.dumps(mapping_payload, ensure_ascii=True)}],
        system=MAPPING_SYSTEM_PROMPT,
        max_tokens=4096,
        timeout_seconds=90.0,
    )
    if response is None:
        return {}

    cleaned = _strip_code_fence(response)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Criteria mapping response was not valid JSON")
        return {}

    if not isinstance(parsed, list):
        logger.warning("Criteria mapping response was not a list")
        return {}

    mapped: dict[int, dict] = {}
    for item in parsed:
        if not isinstance(item, dict):
            continue
        source_order = item.get("source_order")
        if not isinstance(source_order, int):
            continue
        mapped[source_order] = item
    return mapped


def _criteria_type_from_value(value: str | None) -> CriteriaType | None:
    normalized = (value or "").strip().lower()
    if normalized == CriteriaType.inclusion.value:
        return CriteriaType.inclusion
    if normalized == CriteriaType.exclusion.value:
        return CriteriaType.exclusion
    return None


def _confidence_from_value(value: str | None) -> ConfidenceLevel:
    normalized = (value or "").strip().lower()
    if normalized == ConfidenceLevel.high.value:
        return ConfidenceLevel.high
    return ConfidenceLevel.needs_review


def _set_row_needs_review(row: ParsedCriterion) -> None:
    row.expression = None
    row.confidence = ConfidenceLevel.needs_review
    row.manual_review_required = True
    row.parse_status = CriteriaParseStatus.needs_review


def _apply_parse_status_from_confidence(row: ParsedCriterion) -> None:
    if row.confidence == ConfidenceLevel.high and not row.manual_review_required:
        row.parse_status = CriteriaParseStatus.parsed
    else:
        row.parse_status = CriteriaParseStatus.needs_review


async def _attach_expression_mappings(criteria: list[ParsedCriterion]) -> None:
    mapping_by_order = await _map_structured_expressions(criteria)
    for row in criteria:
        if row.source_order is None:
            continue
        mapping = mapping_by_order.get(row.source_order)
        if mapping is None:
            continue

        expression = mapping.get("expression")
        if expression is not None and not isinstance(expression, dict):
            expression = None

        confidence = _confidence_from_value(mapping.get("confidence"))
        manual_review_required = bool(mapping.get("manual_review_required", expression is None))

        if expression is None:
            _set_row_needs_review(row)
            continue

        try:
            validate_expression(expression)
        except Exception:
            _set_row_needs_review(row)
            continue

        row.expression = expression
        row.confidence = confidence
        row.manual_review_required = manual_review_required
        _apply_parse_status_from_confidence(row)


async def parse_criteria_from_text(text: str) -> list[ParsedCriterion]:
    criteria = _extract_row_level_criteria(text)
    if not criteria:
        return []

    await _attach_expression_mappings(criteria)
    for row in criteria:
        if row.from_fallback:
            _set_row_needs_review(row)
    return criteria


async def parse_criteria_with_ai_from_text(text: str) -> list[ParsedCriterion]:
    if not text.strip():
        return []

    response = await chat_completion(
        messages=[{"role": "user", "content": text}],
        system=AI_EXTRACTION_SYSTEM_PROMPT,
        max_tokens=4096,
        timeout_seconds=180.0,
    )
    if response is None:
        return []

    cleaned = _strip_code_fence(response)
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("AI criteria extraction response was not valid JSON")
        return []

    if not isinstance(parsed, list):
        logger.warning("AI criteria extraction response was not a list")
        return []

    rows: list[ParsedCriterion] = []
    seen: set[tuple[str, str]] = set()
    source_order = 1

    for item in parsed:
        if not isinstance(item, dict):
            continue

        criterion_type = _criteria_type_from_value(str(item.get("type") or ""))
        criterion_text = _normalize_text(str(item.get("text") or ""))
        if criterion_type is None or not criterion_text:
            continue

        dedupe_key = (criterion_type.value, criterion_text.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        confidence = _confidence_from_value(str(item.get("confidence") or ""))
        parse_status = CriteriaParseStatus.parsed if confidence == ConfidenceLevel.high else CriteriaParseStatus.needs_review
        quote_snippet_raw = item.get("quote")
        quote_snippet = _normalize_text(str(quote_snippet_raw)) if quote_snippet_raw else None

        rows.append(
            ParsedCriterion(
                type=criterion_type,
                text=criterion_text,
                expression=None,
                confidence=confidence,
                manual_review_required=parse_status != CriteriaParseStatus.parsed,
                source_order=source_order,
                section_label=AI_SECTION_LABELS[criterion_type],
                parse_status=parse_status,
                quote_snippet=quote_snippet,
            )
        )
        source_order += 1

    return rows
