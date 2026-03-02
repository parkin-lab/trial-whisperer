"""
LLM-based criteria parser using OpenClaw gateway (Claude).
Called at ingestion time only - never during screening evaluation.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from app.models.enums import ConfidenceLevel, CriteriaType
from app.services.llm import chat_completion

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical trial protocol parser. Extract eligibility criteria from protocol text.

For each criterion, output a JSON object with:
- type: "inclusion" or "exclusion"
- text: exact text of the criterion
- expression: structured rule (see schema below) or null if too complex
- confidence: "high" if cleanly mapped to expression, "needs_review" otherwise
- manual_review_required: true if criterion is ambiguous, investigator-dependent, or cannot be structured

Expression schema:
{"op": "gte"|"lte"|"gt"|"lt"|"eq"|"neq", "field": str, "value": number|str|bool, "unit": str|null}
{"op": "is_true"|"is_false", "field": str}
{"op": "in"|"not_in", "field": str, "values": []}
{"op": "within_days", "field": str, "days": int}
{"op": "and"|"or", "operands": [...]} 
{"op": "not", "operands": [single_expr]}

Field naming conventions:
- age (years), ecog (0-4), anc (cells/uL), plt (x10^3/uL), cr (mg/dL), bili (mg/dL), ast (U/L), alt (U/L), lvef (%)
- prior_venetoclax, prior_hma, prior_transplant, prior_car_t (boolean fields)
- disease_status: "newly_diagnosed"|"relapsed"|"refractory"|"cr1"|"cr2_plus"
- indication: "aml"|"all"|"lymphoma"|"mm"|"transplant"|"gvhd"

Set confidence="needs_review" for:
- Compound criteria with multiple conditions
- "as determined by investigator" or "per investigator discretion"
- Local lab ULN references without specific values
- Vague qualifiers ("adequate", "acceptable")

Never invent values. If uncertain, set expression=null and confidence="needs_review".
Return ONLY a JSON array - no markdown, no explanation."""


@dataclass
class ParsedCriterion:
    type: CriteriaType
    text: str
    expression: dict | None
    confidence: ConfidenceLevel
    manual_review_required: bool


async def parse_criteria_from_text(text: str) -> list[ParsedCriterion]:
    """Parse eligibility criteria from protocol text using Claude via OpenClaw gateway."""
    result = await chat_completion(
        messages=[
            {
                "role": "user",
                "content": f"Extract all eligibility criteria from this protocol text:\n\n{text[:15000]}",
            }
        ],
        system=SYSTEM_PROMPT,
        max_tokens=4096,
    )

    if result is None:
        logger.warning("LLM unavailable - returning empty criteria list")
        return []

    cleaned = result.strip()
    if cleaned.startswith("```"):
        parts = cleaned.split("```")
        cleaned = parts[1] if len(parts) > 1 else cleaned
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        raw_list = json.loads(cleaned)
        if not isinstance(raw_list, list):
            logger.warning("LLM returned non-list response")
            return []
    except json.JSONDecodeError as exc:
        logger.exception("Failed to parse LLM JSON response: %s | Raw: %s", exc, cleaned[:500])
        return []

    criteria: list[ParsedCriterion] = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        try:
            criteria.append(
                ParsedCriterion(
                    type=CriteriaType(item.get("type", "inclusion")),
                    text=str(item.get("text", "")),
                    expression=item.get("expression") or None,
                    confidence=ConfidenceLevel(item.get("confidence", "needs_review")),
                    manual_review_required=bool(item.get("manual_review_required", False)),
                )
            )
        except (ValueError, KeyError) as exc:
            logger.warning("Skipping malformed criterion: %s - %s", exc, item)
            continue

    return criteria
