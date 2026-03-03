from uuid import uuid4

import pytest

from app.models.enums import TrialExtractionStatus, TrialStatus
from app.models.trial import Trial
from app.schemas.awareness import AwarenessCardGenerateRequest
from app.services import awareness_card

pytestmark = pytest.mark.asyncio


def _trial(**overrides) -> Trial:
    payload = {
        "nickname": "Awareness Trial",
        "created_by": uuid4(),
        "status": TrialStatus.draft,
        "extraction_status": TrialExtractionStatus.needs_review,
        "trial_title": "Phase 2 Study of XYZ in AML",
        "nct_id": "NCT12345678",
        "indication": "aml",
        "phase": "Phase 2",
        "sponsor": "Trial Sponsor",
    }
    payload.update(overrides)
    return Trial(**payload)


async def test_generate_awareness_card_with_full_trial_metadata(monkeypatch):
    trial = _trial()

    async def _mock_chat_completion(*args, **kwargs):
        del args, kwargs
        return '{"trial_purpose":"Evaluate efficacy and safety in relapsed disease."}'

    monkeypatch.setattr(awareness_card, "chat_completion", _mock_chat_completion)

    card = await awareness_card.build_awareness_card(
        trial,
        AwarenessCardGenerateRequest(
            disease_setting="Relapsed/refractory AML",
            mechanism="Targeted therapy",
        ),
    )

    lines = card.text_card.splitlines()
    assert lines[0] == "Phase 2 Study of XYZ in AML"
    assert lines[1] == "RELAPSED/REFRACTORY AML | Phase 2 | NCT12345678"
    assert lines[2] == "Targeted therapy"
    assert lines[3] == "Evaluate efficacy and safety in relapsed disease."
    assert all("TBD" not in line for line in lines)
    assert card.fields["mechanism"] == "Targeted therapy"
    assert card.fields["trial_purpose"] == "Evaluate efficacy and safety in relapsed disease."


async def test_generate_awareness_card_omits_optional_lines_when_missing(monkeypatch):
    trial = _trial(
        trial_title=None,
        nct_id=None,
        indication=None,
        phase=None,
        sponsor=None,
    )

    async def _mock_chat_completion(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr(awareness_card, "chat_completion", _mock_chat_completion)

    card = await awareness_card.build_awareness_card(trial, AwarenessCardGenerateRequest())

    assert card.text_card == "Awareness Trial"
    assert card.visual.subtitle == ""
    assert card.visual.lines == []
    assert "TBD" not in card.text_card


async def test_generate_awareness_card_derives_mechanism_from_title(monkeypatch):
    trial = _trial(trial_title="A Phase 2 Study of CAR-T Therapy in AML")

    async def _mock_chat_completion(*args, **kwargs):
        del args, kwargs
        return '{"trial_purpose":"Assess activity in adults with relapsed AML."}'

    monkeypatch.setattr(awareness_card, "chat_completion", _mock_chat_completion)

    card = await awareness_card.build_awareness_card(trial, AwarenessCardGenerateRequest())

    assert card.fields["mechanism"] == "CAR-T cell therapy"


async def test_generate_awareness_card_enforces_visual_line_length():
    trial = _trial()
    long_text = "x" * 300

    card = await awareness_card.build_awareness_card(
        trial,
        AwarenessCardGenerateRequest(
            mechanism=long_text,
            trial_purpose=long_text,
        ),
    )

    assert len(card.visual.lines) <= 4
    assert all(len(line) <= 120 for line in card.visual.lines)
