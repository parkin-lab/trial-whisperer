from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.engine.evaluator import EvaluationResult, evaluate_all_trials
from app.engine.tier1_fields import FieldDefinition, TIER1_FIELDS
from app.models.audit import AuditLog
from app.models.enums import TrialStatus
from app.models.trial import Trial, TrialCriteria
from app.models.user import User
from app.schemas.trial import ScreeningRequest, ScreeningResponse

ENGINE_VERSION = "1.0.0"

router = APIRouter(tags=["screener"])


@router.get("/screen/tier1-fields", response_model=dict[str, list[FieldDefinition]])
async def list_tier1_fields(
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, list[FieldDefinition]]:
    return TIER1_FIELDS


@router.post("/screen", response_model=ScreeningResponse)
async def screen_trials(
    payload: ScreeningRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ScreeningResponse:
    trial_query = select(Trial).where(Trial.status == TrialStatus.active, Trial.indication == payload.indication)
    if payload.trial_ids:
        trial_query = trial_query.where(Trial.id.in_(payload.trial_ids))

    trial_result = await db.execute(trial_query.order_by(Trial.created_at.desc()))
    trials = trial_result.scalars().all()
    if not trials:
        return ScreeningResponse(results=[], screened_at=datetime.now(UTC), engine_version=ENGINE_VERSION)

    trial_ids = [trial.id for trial in trials]
    criteria_result = await db.execute(select(TrialCriteria).where(TrialCriteria.trial_id.in_(trial_ids)))
    criteria_rows = criteria_result.scalars().all()

    grouped: dict[UUID, list[TrialCriteria]] = {trial.id: [] for trial in trials}
    latest_versions: dict[UUID, int] = {}
    for row in criteria_rows:
        latest_versions[row.trial_id] = max(latest_versions.get(row.trial_id, 0), row.document_version)

    for row in criteria_rows:
        if latest_versions.get(row.trial_id) == row.document_version:
            grouped[row.trial_id].append(row)

    eval_input = [
        {
            "trial_id": trial.id,
            "trial_name": trial.nickname,
            "criteria": grouped.get(trial.id, []),
        }
        for trial in trials
    ]
    results = evaluate_all_trials(eval_input, payload.patient_data)

    order = {
        EvaluationResult.MET: 0,
        EvaluationResult.INCOMPLETE: 1,
        EvaluationResult.MANUAL_REVIEW: 2,
        EvaluationResult.NOT_MET: 3,
    }
    results.sort(key=lambda item: (order.get(item.overall, 99), item.trial_name or ""))

    for item in results:
        audit_row = AuditLog(
            user_id=user.id,
            indication=payload.indication,
            criteria_version_hash=item.version_hash,
            engine_version=ENGINE_VERSION,
            screen_results={
                "trial_id": item.trial_id,
                "overall": item.overall.value,
                "criteria": {entry.criterion_id: entry.result.value for entry in item.criteria_results},
            },
        )
        db.add(audit_row)

    await db.commit()

    return ScreeningResponse(
        results=results,
        screened_at=datetime.now(UTC),
        engine_version=ENGINE_VERSION,
    )
