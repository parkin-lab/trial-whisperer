from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config import get_settings
from app.engine.schema import validate_expression
from app.models.enums import ConfidenceLevel, CriteriaType
from app.schemas.trial import ParsedCriterion

settings = get_settings()

_PLACEHOLDER_EXPRESSION = {"op": "is_true", "field": "manual_review_placeholder"}

_SYSTEM_PROMPT = """
You are parsing clinical trial protocol eligibility criteria.

Requirements:
- Extract each inclusion and exclusion criterion as a separate item.
- For each criterion, attempt to map it to a structured expression with this schema:
  - Comparison: gte, lte, gt, lt, eq, neq
  - Boolean: is_true, is_false
  - Set membership: in, not_in
  - Compound: and, or, not
  - Temporal: within_days (uses fields: op, field, days)
- Return a JSON object with key \"criteria\" and a value that is an array.
- Each array item must contain: type, text, expression, confidence, manual_review_required.
- type must be inclusion or exclusion.
- confidence must be high or needs_review.
- Set confidence=high only when criterion maps cleanly to a single typed expression.
- Set confidence=needs_review for compound criteria, free-text qualifiers, investigator discretion,
  local lab ULN references, or temporal logic without a clear window.
- Never invent values. If uncertain, set confidence=needs_review.
- If confidence=needs_review and expression is uncertain, provide a minimal placeholder expression.
- Return valid JSON only.
""".strip()


def _placeholder_criterion(item_type: CriteriaType, text: str) -> ParsedCriterion:
    return ParsedCriterion(
        type=item_type,
        text=text,
        expression=_PLACEHOLDER_EXPRESSION,
        confidence=ConfidenceLevel.needs_review,
        manual_review_required=True,
    )


def _extract_fallback_items(text: str) -> list[ParsedCriterion]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return []

    items: list[ParsedCriterion] = []
    current_type = CriteriaType.inclusion
    bullet_pattern = re.compile(r"^(?:[-*]|\d+[.)])\s+")

    for line in lines:
        lowered = line.lower()
        if "inclusion" in lowered and len(line) <= 80:
            current_type = CriteriaType.inclusion
            continue
        if "exclusion" in lowered and len(line) <= 80:
            current_type = CriteriaType.exclusion
            continue

        cleaned = bullet_pattern.sub("", line).strip()
        if len(cleaned) < 4:
            continue
        items.append(_placeholder_criterion(current_type, cleaned))

    if items:
        return items

    sentence_candidates = [piece.strip() for piece in re.split(r"[\n.;]", text) if piece.strip()]
    return [_placeholder_criterion(CriteriaType.inclusion, piece) for piece in sentence_candidates if len(piece) >= 4]


def _validate_item(raw_item: dict[str, Any]) -> ParsedCriterion:
    base = ParsedCriterion.model_validate(raw_item)

    if base.confidence == ConfidenceLevel.high:
        try:
            validate_expression(base.expression)
        except Exception:
            return base.model_copy(
                update={
                    "confidence": ConfidenceLevel.needs_review,
                    "manual_review_required": True,
                    "expression": _PLACEHOLDER_EXPRESSION,
                }
            )

    if base.confidence == ConfidenceLevel.needs_review:
        if not base.manual_review_required:
            base = base.model_copy(update={"manual_review_required": True})
        if not isinstance(base.expression, dict) or not base.expression:
            base = base.model_copy(update={"expression": _PLACEHOLDER_EXPRESSION})

    return base


async def parse_criteria_from_text(text: str, model: str = "gpt-4o") -> list[ParsedCriterion]:
    """
    Call OpenAI API to extract and structure eligibility criteria from protocol text.
    Returns list of ParsedCriterion with expression + confidence.
    Falls back to raw text with confidence=needs_review if parsing fails.
    """
    if not text.strip():
        return []

    api_key = settings.openai_api_key
    if not api_key:
        return _extract_fallback_items(text)

    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Extract eligibility criteria from this protocol text and return JSON with key 'criteria'.\n\n"
                    f"{text}"
                ),
            },
        ],
    }

    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            response.raise_for_status()

        content = response.json()["choices"][0]["message"]["content"]
        decoded = json.loads(content)

        if isinstance(decoded, list):
            raw_items = decoded
        else:
            raw_items = decoded.get("criteria", [])

        parsed = [_validate_item(item) for item in raw_items if isinstance(item, dict)]
        return parsed or _extract_fallback_items(text)
    except Exception:
        return _extract_fallback_items(text)
