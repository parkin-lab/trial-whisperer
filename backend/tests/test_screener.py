from __future__ import annotations

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.enums import ConfidenceLevel, CriteriaType, Indication, TrialStatus, UserRole
from app.models.trial import Trial, TrialCriteria
from app.models.user import User
from app.services.auth import hash_password


async def _create_user(db_session) -> User:
    user = User(
        email="screen@example.com",
        name="screen",
        hashed_password=hash_password("password123"),
        role=UserRole.coordinator,
        active=True,
        domain="example.com",
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _login(client) -> str:
    res = await client.post("/auth/login", json={"email": "screen@example.com", "password": "password123"})
    assert res.status_code == 200
    return res.json()["access_token"]


async def test_screen_endpoint_orders_results_and_logs_audit(client, db_session):
    user = await _create_user(db_session)

    eligible_trial = Trial(
        nickname="Eligible Trial",
        indication=Indication.aml,
        status=TrialStatus.active,
        created_by=user.id,
        nct_id="NCT00000001",
    )
    ineligible_trial = Trial(
        nickname="Ineligible Trial",
        indication=Indication.aml,
        status=TrialStatus.active,
        created_by=user.id,
        nct_id="NCT00000002",
    )
    db_session.add_all([eligible_trial, ineligible_trial])
    await db_session.flush()

    db_session.add_all(
        [
            TrialCriteria(
                trial_id=eligible_trial.id,
                document_version=1,
                type=CriteriaType.inclusion,
                text="Age >= 18",
                expression={"op": "gte", "field": "age", "value": 18, "unit": "years"},
                confidence=ConfidenceLevel.high,
                manual_review_required=False,
                rule_version="1.0.0",
            ),
            TrialCriteria(
                trial_id=ineligible_trial.id,
                document_version=1,
                type=CriteriaType.inclusion,
                text="Age >= 70",
                expression={"op": "gte", "field": "age", "value": 70, "unit": "years"},
                confidence=ConfidenceLevel.high,
                manual_review_required=False,
                rule_version="1.0.0",
            ),
        ]
    )
    await db_session.commit()

    token = await _login(client)
    response = await client.post(
        "/screen",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "indication": "aml",
            "patient_data": {"age": 65},
            "trial_ids": None,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["engine_version"] == "1.0.0"
    assert [item["trial_name"] for item in payload["results"]] == ["Eligible Trial", "Ineligible Trial"]
    assert [item["overall"] for item in payload["results"]] == ["met", "not_met"]

    audit_rows = (await db_session.execute(select(AuditLog))).scalars().all()
    assert len(audit_rows) == 2
    assert all("age" not in str(row.screen_results) for row in audit_rows)
    assert all("criteria" in row.screen_results for row in audit_rows)
