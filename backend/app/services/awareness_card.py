from __future__ import annotations

import json
import re
from collections.abc import Sequence

from app.models.trial import Trial
from app.schemas.awareness import AwarenessCardGenerateRequest, AwarenessCardResponse, AwarenessCardVisual
from app.services.llm import chat_completion

MAX_LINE_LENGTH = 120
MAX_VISUAL_LINES = 4

_SYSTEM_PROMPT = """You write concise trial-awareness snippets for clinicians.
Return JSON only with key \"trial_purpose\".
Value must be one neutral sentence, no labels, no markdown."""


def _clean_optional(value: str | None) -> str | None:
    cleaned = re.sub(r"\s+", " ", (value or "").strip())
    return cleaned or None


def _enum_to_text(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        cleaned = _clean_optional(str(getattr(value, "value")))
        return cleaned
    return _clean_optional(str(value))


def _truncate_line(value: str, limit: int = MAX_LINE_LENGTH) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 3:
        return cleaned[:limit]
    return f"{cleaned[: limit - 3].rstrip()}..."


def _cap_lines(lines: Sequence[str]) -> list[str]:
    capped: list[str] = []
    for line in lines:
        cleaned = _clean_optional(line)
        if not cleaned:
            continue
        capped.append(_truncate_line(cleaned))
        if len(capped) >= MAX_VISUAL_LINES:
            break
    return capped


def _clean_title(value: str | None, fallback: str | None) -> str:
    source = _clean_optional(value) or _clean_optional(fallback) or "Trial"
    source = re.sub(r"^protocol(?:\s+synopsis)?\s*[:\-]\s*", "", source, flags=re.IGNORECASE)
    return _truncate_line(source)


def _build_subtitle(indication: str | None, phase: str | None, nct_id: str | None) -> str:
    parts: list[str] = []
    if indication:
        parts.append(indication.upper())
    if phase:
        parts.append(phase)
    if nct_id:
        parts.append(nct_id)
    if not parts:
        return ""
    return _truncate_line(" | ".join(parts))


def _infer_mechanism_phrase(*, title: str | None, document_title: str | None) -> str | None:
    source = f"{title or ''} {document_title or ''}".lower()
    if not source.strip():
        return None

    if "car-t" in source or "cart" in source or "chimeric antigen receptor" in source:
        return "CAR-T cell therapy"
    if "bispecific" in source or "bi-specific" in source or "bsab" in source:
        return "Bispecific antibody"
    if "antibody-drug conjugate" in source or "antibody drug conjugate" in source or " adc " in f" {source} ":
        return "Antibody-drug conjugate"
    if "t-cell engager" in source or "t cell engager" in source:
        return "T-cell engager"
    if "checkpoint inhibitor" in source or "pd-1" in source or "pd-l1" in source or "ctla-4" in source:
        return "Checkpoint inhibitor"
    if "cell therapy" in source:
        return "Cell therapy"
    return None


def _parse_llm_json(response_text: str | None) -> dict[str, str]:
    if not response_text:
        return {}

    text = response_text.strip()
    candidates = [text]
    block_match = re.search(r"\{[\s\S]*\}", text)
    if block_match:
        candidates.append(block_match.group(0))

    for candidate in candidates:
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return {str(k): str(v) for k, v in data.items() if isinstance(v, str)}
        except json.JSONDecodeError:
            continue
    return {}


async def _generate_trial_purpose(context_fields: dict[str, str]) -> str | None:
    user_prompt = (
        "Generate one concise trial-purpose line from this context.\n"
        "Return JSON only.\n"
        f"{json.dumps(context_fields, ensure_ascii=True)}"
    )
    response = await chat_completion(
        messages=[{"role": "user", "content": user_prompt}],
        system=_SYSTEM_PROMPT,
        max_tokens=120,
    )
    parsed = _parse_llm_json(response)
    return _clean_optional(parsed.get("trial_purpose"))


async def build_awareness_card(trial: Trial, overrides: AwarenessCardGenerateRequest) -> AwarenessCardResponse:
    title = _clean_title(trial.trial_title or trial.document_title, trial.nickname)
    indication = _clean_optional(overrides.disease_setting) or _enum_to_text(trial.indication)
    phase = _clean_optional(trial.phase)
    nct_id = _clean_optional(trial.nct_id)

    subtitle = _build_subtitle(indication, phase, nct_id)

    mechanism = _clean_optional(overrides.mechanism)
    if not mechanism:
        mechanism = _clean_optional(overrides.intervention_class)
    if not mechanism:
        mechanism = _clean_optional(_infer_mechanism_phrase(title=trial.trial_title, document_title=trial.document_title))

    trial_purpose = _clean_optional(overrides.trial_purpose)
    if not trial_purpose:
        trial_purpose = _clean_optional(overrides.why_it_matters)
    if not trial_purpose:
        trial_purpose = _clean_optional(overrides.when_to_think)
    if not trial_purpose:
        trial_purpose = await _generate_trial_purpose(
            {
                "title": title,
                "indication": indication or "",
                "phase": phase or "",
                "nct_id": nct_id or "",
                "mechanism": mechanism or "",
            }
        )

    lines = _cap_lines([mechanism or "", trial_purpose or ""])

    visual = AwarenessCardVisual(
        title=title,
        subtitle=subtitle,
        lines=lines,
    )

    text_lines: list[str] = [visual.title]
    if visual.subtitle and visual.subtitle not in text_lines:
        text_lines.append(visual.subtitle)
    for line in visual.lines:
        if line and line not in text_lines:
            text_lines.append(line)

    fields: dict[str, str] = {"title": visual.title}
    if indication:
        fields["indication"] = indication
    if phase:
        fields["phase"] = phase
    if nct_id:
        fields["nct_id"] = nct_id
    if mechanism:
        fields["mechanism"] = _truncate_line(mechanism)
    if trial_purpose:
        fields["trial_purpose"] = _truncate_line(trial_purpose)

    text_card = "\n".join(text_lines)
    return AwarenessCardResponse(text_card=text_card, visual=visual, fields=fields)
