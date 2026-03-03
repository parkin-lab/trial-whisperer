from __future__ import annotations

import json
import re
from collections.abc import Sequence

from app.models.trial import Trial
from app.schemas.awareness import AwarenessCardGenerateRequest, AwarenessCardResponse, AwarenessCardVisual
from app.services.llm import chat_completion

PLACEHOLDER = "TBD"
MAX_LINE_LENGTH = 120
MAX_VISUAL_LINES = 7

_SYSTEM_PROMPT = """You write concise, trial-level awareness cards for clinicians.
Return JSON only with keys "why_it_matters" and "when_to_think".
Each value must be one sentence, neutral tone, no patient-fit language."""


def _string_or_placeholder(value: str | None) -> str:
    cleaned = (value or "").strip()
    return cleaned if cleaned else PLACEHOLDER


def _enum_to_text(value: object) -> str:
    if value is None:
        return PLACEHOLDER
    if hasattr(value, "value"):
        return str(getattr(value, "value")).strip() or PLACEHOLDER
    return _string_or_placeholder(str(value))


def _truncate_line(value: str, limit: int = MAX_LINE_LENGTH) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip()
    if len(cleaned) <= limit:
        return cleaned
    if limit <= 3:
        return cleaned[:limit]
    return f"{cleaned[: limit - 3].rstrip()}..."


def _cap_lines(lines: Sequence[str]) -> list[str]:
    return [_truncate_line(line) for line in list(lines)[:MAX_VISUAL_LINES]]


def _build_subtitle(indication: str, phase: str, nct_id: str) -> str:
    return _truncate_line(f"{indication} | {phase} | {nct_id}")


def _infer_intervention_class(*, title: str | None, document_title: str | None) -> str | None:
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


def _build_trial_detail_line(*, title: str | None, phase: str | None, sponsor: str | None, nct_id: str | None) -> str:
    segments: list[str] = []
    if title and title.strip():
        segments.append(f"Trial title: {title.strip()}")
    if phase and phase.strip():
        segments.append(f"Phase: {phase.strip()}")
    if sponsor and sponsor.strip():
        segments.append(f"Sponsor: {sponsor.strip()}")
    if nct_id and nct_id.strip():
        segments.append(f"NCT: {nct_id.strip()}")
    if not segments:
        return "Trial details: TBD"
    return _truncate_line(" | ".join(segments))


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


async def _generate_missing_fields(context_fields: dict[str, str]) -> dict[str, str]:
    user_prompt = (
        "Generate awareness text for this trial context.\n"
        "Return JSON only.\n"
        f"{json.dumps(context_fields, ensure_ascii=True)}"
    )
    response = await chat_completion(
        messages=[{"role": "user", "content": user_prompt}],
        system=_SYSTEM_PROMPT,
        max_tokens=300,
    )
    parsed = _parse_llm_json(response)
    return {
        "why_it_matters": _string_or_placeholder(parsed.get("why_it_matters")),
        "when_to_think": _string_or_placeholder(parsed.get("when_to_think")),
    }


async def build_awareness_card(trial: Trial, overrides: AwarenessCardGenerateRequest) -> AwarenessCardResponse:
    indication = _enum_to_text(trial.indication)
    title = _string_or_placeholder(trial.trial_title or trial.document_title)
    phase = _string_or_placeholder(trial.phase)
    sponsor = _string_or_placeholder(trial.sponsor)
    nct_id = _string_or_placeholder(trial.nct_id)
    intervention_class = _infer_intervention_class(title=trial.trial_title, document_title=trial.document_title)

    fields = {
        "title": _truncate_line(title),
        "indication": _truncate_line(indication),
        "phase": _truncate_line(phase),
        "sponsor": _truncate_line(sponsor),
        "nct_id": _truncate_line(nct_id),
        "disease_setting": _truncate_line(overrides.disease_setting or indication),
        "intervention_class": _truncate_line(overrides.intervention_class or intervention_class or PLACEHOLDER),
        "why_it_matters": _truncate_line(overrides.why_it_matters or ""),
        "when_to_think": _truncate_line(overrides.when_to_think or ""),
        "referral_contact": _truncate_line(overrides.referral_contact or PLACEHOLDER),
    }

    needs_llm = not overrides.why_it_matters or not overrides.when_to_think
    if needs_llm:
        generated = await _generate_missing_fields(
            {
                "title": fields["title"],
                "indication": fields["indication"],
                "phase": fields["phase"],
                "sponsor": fields["sponsor"],
                "nct_id": fields["nct_id"],
                "disease_setting": fields["disease_setting"],
                "intervention_class": fields["intervention_class"],
            }
        )
        if not overrides.why_it_matters:
            fields["why_it_matters"] = _truncate_line(generated["why_it_matters"])
        if not overrides.when_to_think:
            fields["when_to_think"] = _truncate_line(generated["when_to_think"])

    fields["why_it_matters"] = _string_or_placeholder(fields["why_it_matters"])
    fields["when_to_think"] = _string_or_placeholder(fields["when_to_think"])

    visual_lines = _cap_lines(
        [
            f"Disease setting: {fields['disease_setting']}",
            f"Intervention class: {fields['intervention_class']}",
            f"Why it matters: {fields['why_it_matters']}",
            f"When to think: {fields['when_to_think']}",
            f"Sponsor: {fields['sponsor']}",
            f"Referral contact: {fields['referral_contact']}",
        ]
    )

    visual = AwarenessCardVisual(
        title=fields["title"],
        subtitle=_build_subtitle(fields["indication"], fields["phase"], fields["nct_id"]),
        lines=visual_lines,
    )

    text_card = "\n".join(
        [
            visual.title,
            visual.subtitle,
            _build_trial_detail_line(
                title=trial.trial_title or trial.document_title,
                phase=trial.phase,
                sponsor=trial.sponsor,
                nct_id=trial.nct_id,
            ),
            *visual.lines,
        ]
    )
    return AwarenessCardResponse(text_card=text_card, visual=visual, fields=fields)
