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
        return '{"why_it_matters":"Offers novel mechanism in relapsed disease.","when_to_think":"Consider after standard options are exhausted."}'

    monkeypatch.setattr(awareness_card, "chat_completion", _mock_chat_completion)

    card = await awareness_card.build_awareness_card(
        trial,
        AwarenessCardGenerateRequest(
            disease_setting="Relapsed/refractory AML",
            intervention_class="Targeted therapy",
            referral_contact="trial-team@example.org",
        ),
    )

    assert card.fields["title"] == "Phase 2 Study of XYZ in AML"
    assert card.fields["indication"] == "aml"
    assert card.fields["phase"] == "Phase 2"
    assert card.fields["sponsor"] == "Trial Sponsor"
    assert card.fields["nct_id"] == "NCT12345678"
    assert card.fields["why_it_matters"] == "Offers novel mechanism in relapsed disease."
    assert card.fields["when_to_think"] == "Consider after standard options are exhausted."
    assert card.text_card


async def test_generate_awareness_card_uses_placeholders_for_missing_metadata(monkeypatch):
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

    assert card.fields["title"] == "TBD"
    assert card.fields["indication"] == "TBD"
    assert card.fields["phase"] == "TBD"
    assert card.fields["sponsor"] == "TBD"
    assert card.fields["nct_id"] == "TBD"
    assert card.fields["why_it_matters"] == "TBD"
    assert card.fields["when_to_think"] == "TBD"


async def test_generate_awareness_card_enforces_visual_line_length():
    trial = _trial()
    long_text = "x" * 300

    card = await awareness_card.build_awareness_card(
        trial,
        AwarenessCardGenerateRequest(
            disease_setting=long_text,
            intervention_class=long_text,
            why_it_matters=long_text,
            when_to_think=long_text,
            referral_contact=long_text,
        ),
    )

    assert len(card.visual.lines) <= 7
    assert all(len(line) <= 120 for line in card.visual.lines)
