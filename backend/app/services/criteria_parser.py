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

SECTION_LABELS = {
    CriteriaType.inclusion: "Inclusion",
    CriteriaType.exclusion: "Exclusion",
}

EXCLUSION_HEADING_RE = re.compile(r"\bexclusion(?:\s+criteria)?\b", re.IGNORECASE)
INCLUSION_HEADING_RE = re.compile(r"\binclusion(?:\s+criteria)?\b|\beligibility\s+criteria\b", re.IGNORECASE)
BULLET_PREFIX_RE = re.compile(r"^\s*(?:[-*•●▪‣]\s+|\(?\d+[.)]\s+|\(?[a-zA-Z][.)]\s+)")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.;!?])\s+(?=[A-Z0-9(])")


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


def _strip_code_fence(value: str) -> str:
    cleaned = value.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    return cleaned.strip()


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
    text = value.strip()
    if not text:
        return []
    pieces = [piece.strip() for piece in SENTENCE_SPLIT_RE.split(text) if piece.strip()]
    return pieces if pieces else [text]


def _extract_row_level_criteria(text: str) -> list[ParsedCriterion]:
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


async def parse_criteria_from_text(text: str) -> list[ParsedCriterion]:
    criteria = _extract_row_level_criteria(text)
    if not criteria:
        return []

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

        confidence_raw = mapping.get("confidence", ConfidenceLevel.needs_review.value)
        try:
            confidence = ConfidenceLevel(confidence_raw)
        except ValueError:
            confidence = ConfidenceLevel.needs_review

        manual_review_required = bool(mapping.get("manual_review_required", expression is None))

        if expression is None:
            row.expression = None
            row.confidence = ConfidenceLevel.needs_review
            row.manual_review_required = True
            row.parse_status = CriteriaParseStatus.needs_review
            continue

        try:
            validate_expression(expression)
        except Exception:
            row.expression = None
            row.confidence = ConfidenceLevel.needs_review
            row.manual_review_required = True
            row.parse_status = CriteriaParseStatus.needs_review
            continue

        row.expression = expression
        row.confidence = confidence
        row.manual_review_required = manual_review_required
        row.parse_status = CriteriaParseStatus.parsed

    return criteria
