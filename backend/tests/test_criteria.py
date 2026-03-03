import uuid

import pytest
from sqlalchemy import select

from app.models.enums import ConfidenceLevel, CriteriaParseStatus, CriteriaType, TrialExtractionStatus, TrialStatus, UserRole
from app.models.trial import Trial, TrialCriteria, TrialDocument
from app.models.user import User
from app.routers import criteria as criteria_router
from app.services.auth import hash_password
from app.services.criteria_parser import ParsedCriterion, parse_criteria_from_text

pytestmark = pytest.mark.asyncio


async def _create_user(db_session, *, role: UserRole) -> User:
    user = User(
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        name="test-user",
        hashed_password=hash_password("password123"),
        role=role,
        active=True,
        domain="example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login(client, email: str) -> str:
    response = await client.post("/auth/login", json={"email": email, "password": "password123"})
    assert response.status_code == 200
    return response.json()["access_token"]


async def _create_trial_with_document(db_session, created_by) -> tuple[Trial, TrialDocument]:
    trial = Trial(
        nickname=f"trial-{uuid.uuid4().hex[:6]}",
        status=TrialStatus.draft,
        extraction_status=TrialExtractionStatus.needs_review,
        created_by=created_by,
    )
    db_session.add(trial)
    await db_session.flush()

    doc = TrialDocument(
        trial_id=trial.id,
        version=1,
        filename="protocol.pdf",
        file_path=f"/tmp/{uuid.uuid4().hex}.pdf",
        uploaded_by=created_by,
    )
    db_session.add(doc)
    await db_session.commit()
    await db_session.refresh(trial)
    await db_session.refresh(doc)
    return trial, doc


async def test_parser_splits_one_row_per_bullet(monkeypatch):
    async def _mock_chat_completion(*args, **kwargs):
        del args, kwargs
        return None

    monkeypatch.setattr("app.services.criteria_parser.chat_completion", _mock_chat_completion)

    protocol_text = """
Eligibility Criteria
Inclusion Criteria:
- Age >= 18 years
- ECOG 0-2

Exclusion Criteria:
- Active infection
- Prior allogeneic transplant
"""
    rows = await parse_criteria_from_text(protocol_text)

    assert len(rows) == 4
    assert [item.type for item in rows] == [
        CriteriaType.inclusion,
        CriteriaType.inclusion,
        CriteriaType.exclusion,
        CriteriaType.exclusion,
    ]
    assert [item.source_order for item in rows] == [1, 2, 3, 4]


async def test_failed_expression_parse_stores_null_and_needs_review(client, db_session, monkeypatch):
    reviewer = await _create_user(db_session, role=UserRole.owner)
    token = await _login(client, reviewer.email)
    trial, doc = await _create_trial_with_document(db_session, reviewer.id)

    async def _download_file(file_path):
        del file_path
        return b"pdf", doc.filename

    async def _parse_criteria(text):
        del text
        return [
            ParsedCriterion(
                type=CriteriaType.inclusion,
                text="Creatinine <= 1.5 x ULN",
                expression={"op": "bad_op", "field": "cr", "value": 1.5},
                confidence=ConfidenceLevel.high,
                manual_review_required=False,
                source_order=1,
                section_label="Inclusion",
                parse_status=CriteriaParseStatus.parsed,
            )
        ]

    monkeypatch.setattr(criteria_router, "storage_download_file", _download_file)
    monkeypatch.setattr(criteria_router, "get_local_path_for_extraction", lambda file_path, contents: file_path)
    monkeypatch.setattr(criteria_router, "extract_text", lambda _: "protocol text")
    monkeypatch.setattr(criteria_router, "parse_criteria_from_text", _parse_criteria)

    response = await client.post(
        f"/trials/{trial.id}/criteria/parse",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["expression"] is None
    assert payload[0]["parse_status"] == "needs_review"
    assert payload[0]["confidence"] == "needs_review"
    assert "manual_review_placeholder" not in str(payload)

    row = (
        await db_session.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial.id))
    ).scalar_one()
    assert row.expression is None
    assert row.parse_status == CriteriaParseStatus.needs_review


async def test_list_criteria_filter_by_type(client, db_session):
    reviewer = await _create_user(db_session, role=UserRole.owner)
    token = await _login(client, reviewer.email)
    trial, _ = await _create_trial_with_document(db_session, reviewer.id)

    db_session.add_all(
        [
            TrialCriteria(
                trial_id=trial.id,
                document_version=1,
                type=CriteriaType.inclusion,
                text="Age >= 18",
                expression={"op": "gte", "field": "age", "value": 18},
                confidence=ConfidenceLevel.high,
                manual_review_required=False,
                source_order=1,
                section_label="Inclusion",
                parse_status=CriteriaParseStatus.parsed,
                rule_version="1.0.0",
            ),
            TrialCriteria(
                trial_id=trial.id,
                document_version=1,
                type=CriteriaType.exclusion,
                text="Active infection",
                expression=None,
                confidence=ConfidenceLevel.needs_review,
                manual_review_required=True,
                source_order=2,
                section_label="Exclusion",
                parse_status=CriteriaParseStatus.needs_review,
                rule_version="1.0.0",
            ),
        ]
    )
    await db_session.commit()

    inclusion_res = await client.get(
        f"/trials/{trial.id}/criteria",
        params={"type": "inclusion"},
        headers={"Authorization": f"Bearer {token}"},
    )
    exclusion_res = await client.get(
        f"/trials/{trial.id}/criteria",
        params={"type": "exclusion"},
        headers={"Authorization": f"Bearer {token}"},
    )
    all_res = await client.get(
        f"/trials/{trial.id}/criteria",
        params={"type": "all"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert inclusion_res.status_code == 200
    assert exclusion_res.status_code == 200
    assert all_res.status_code == 200
    assert len(inclusion_res.json()) == 1
    assert inclusion_res.json()[0]["type"] == "inclusion"
    assert len(exclusion_res.json()) == 1
    assert exclusion_res.json()[0]["type"] == "exclusion"
    assert len(all_res.json()) == 2


async def test_delete_criterion_item(client, db_session):
    reviewer = await _create_user(db_session, role=UserRole.owner)
    token = await _login(client, reviewer.email)
    trial, _ = await _create_trial_with_document(db_session, reviewer.id)

    criterion = TrialCriteria(
        trial_id=trial.id,
        document_version=1,
        type=CriteriaType.inclusion,
        text="Age >= 18",
        expression={"op": "gte", "field": "age", "value": 18},
        confidence=ConfidenceLevel.high,
        manual_review_required=False,
        source_order=1,
        section_label="Inclusion",
        parse_status=CriteriaParseStatus.parsed,
        rule_version="1.0.0",
    )
    db_session.add(criterion)
    await db_session.commit()
    await db_session.refresh(criterion)

    response = await client.delete(
        f"/trials/{trial.id}/criteria/{criterion.id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 204

    rows = (await db_session.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial.id))).scalars().all()
    assert rows == []


async def test_approve_reviewed_bulk_endpoint(client, db_session):
    reviewer = await _create_user(db_session, role=UserRole.owner)
    token = await _login(client, reviewer.email)
    trial, _ = await _create_trial_with_document(db_session, reviewer.id)

    parsed_row = TrialCriteria(
        trial_id=trial.id,
        document_version=1,
        type=CriteriaType.inclusion,
        text="Age >= 18",
        expression={"op": "gte", "field": "age", "value": 18},
        confidence=ConfidenceLevel.high,
        manual_review_required=False,
        source_order=1,
        section_label="Inclusion",
        parse_status=CriteriaParseStatus.parsed,
        rule_version="1.0.0",
    )
    manual_only_row = TrialCriteria(
        trial_id=trial.id,
        document_version=1,
        type=CriteriaType.exclusion,
        text="Prior transplant",
        expression=None,
        confidence=ConfidenceLevel.needs_review,
        manual_review_required=True,
        source_order=2,
        section_label="Exclusion",
        parse_status=CriteriaParseStatus.manual_only,
        rule_version="1.0.0",
    )
    needs_review_row = TrialCriteria(
        trial_id=trial.id,
        document_version=1,
        type=CriteriaType.inclusion,
        text="ANC >= 1000",
        expression={"op": "gte", "field": "anc", "value": 1000},
        confidence=ConfidenceLevel.needs_review,
        manual_review_required=False,
        source_order=3,
        section_label="Inclusion",
        parse_status=CriteriaParseStatus.needs_review,
        rule_version="1.0.0",
    )
    empty_text_row = TrialCriteria(
        trial_id=trial.id,
        document_version=1,
        type=CriteriaType.inclusion,
        text="   ",
        expression={"op": "gte", "field": "ecog", "value": 2},
        confidence=ConfidenceLevel.high,
        manual_review_required=False,
        source_order=4,
        section_label="Inclusion",
        parse_status=CriteriaParseStatus.parsed,
        rule_version="1.0.0",
    )
    db_session.add_all([parsed_row, manual_only_row, needs_review_row, empty_text_row])
    await db_session.commit()

    response = await client.post(
        f"/trials/{trial.id}/criteria/approve-reviewed",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["approved_count"] == 2

    rows = (await db_session.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial.id))).scalars().all()
    by_text = {row.text: row for row in rows}
    assert by_text["Age >= 18"].approved_at is not None
    assert by_text["Age >= 18"].parse_status == CriteriaParseStatus.approved
    assert by_text["Prior transplant"].approved_at is not None
    assert by_text["Prior transplant"].parse_status == CriteriaParseStatus.approved
    assert by_text["ANC >= 1000"].approved_at is None
