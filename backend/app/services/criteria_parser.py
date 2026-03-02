import json
import logging

try:
    import anthropic
except ModuleNotFoundError:
    anthropic = None

from app.config import get_settings

settings = get_settings()
logger = logging.getLogger(__name__)


async def parse_criteria_from_text(text: str) -> list[dict]:
    """
    Use Claude to extract and structure eligibility criteria from protocol text.
    Returns list of dicts with: type, text, expression, confidence.
    Falls back to raw text with needs_review if API key not set or call fails.
    """
    if not settings.anthropic_api_key:
        logger.warning("ANTHROPIC_API_KEY not set - returning all criteria as needs_review")
        return _raw_fallback(text)

    if anthropic is None:
        logger.warning("anthropic package not installed - returning all criteria as needs_review")
        return _raw_fallback(text)

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    system_prompt = """You are a clinical trial protocol parser. Extract eligibility criteria from protocol text.

For each criterion, output a JSON object with:
- type: "inclusion" or "exclusion"
- text: exact text of the criterion
- expression: structured rule (see schema) or null if too complex
- confidence: "high" if cleanly mapped to expression, "needs_review" otherwise

Expression schema:
{"op": "gte"|"lte"|"gt"|"lt"|"eq"|"neq", "field": str, "value": number|str|bool, "unit": str|null}
{"op": "is_true"|"is_false", "field": str}
{"op": "in"|"not_in", "field": str, "values": []}
{"op": "within_days", "field": str, "days": int}
{"op": "and"|"or", "operands": [...]}
{"op": "not", "operands": [expr]}

Set confidence=needs_review for: compound criteria, free-text qualifiers, "as determined by investigator", local lab ULN references, vague language.
Never invent values. If uncertain, set expression=null and confidence=needs_review.

Return a JSON array only — no other text."""

    try:
        message = client.messages.create(
            model=settings.llm_model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"Extract all eligibility criteria from this protocol text:\n\n{text[:12000]}",
                }
            ],
            system=system_prompt,
        )
        raw = message.content[0].text.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, list) else _raw_fallback(text)
    except Exception as e:
        logger.exception(f"Criteria parsing failed: {e}")
        return _raw_fallback(text)


def _raw_fallback(text: str) -> list[dict]:
    """Split text into lines and return each as needs_review."""
    lines = [line.strip() for line in text.split("\n") if line.strip() and len(line.strip()) > 20]
    results = []
    for line in lines[:50]:
        results.append(
            {
                "type": "inclusion",
                "text": line,
                "expression": None,
                "confidence": "needs_review",
            }
        )
    return results
