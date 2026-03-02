from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.engine.schema import validate_expression
from app.models.enums import ConfidenceLevel, CriteriaType, UserRole
from app.models.trial import Trial, TrialCriteria, TrialDocument
from app.models.user import User
from app.schemas.trial import CriteriaReviewStatusRead, TrialCriterionRead, TrialCriterionUpdate
from app.services.criteria_parser import parse_criteria_from_text
from app.services.documents import extract_text
from app.services.storage import download_file as storage_download_file, get_local_path_for_extraction

ENGINE_RULE_VERSION = "1.0.0"

router = APIRouter(tags=["criteria"])


async def _get_trial_or_404(db: AsyncSession, trial_id: UUID) -> Trial:
    result = await db.execute(select(Trial).where(Trial.id == trial_id))
    trial = result.scalar_one_or_none()
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")
    return trial


async def _get_criterion_or_404(db: AsyncSession, trial_id: UUID, criterion_id: UUID) -> TrialCriteria:
    result = await db.execute(
        select(TrialCriteria).where(TrialCriteria.id == criterion_id, TrialCriteria.trial_id == trial_id)
    )
    criterion = result.scalar_one_or_none()
    if criterion is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Criterion not found")
    return criterion


@router.post("/trials/{trial_id}/criteria/parse", response_model=list[TrialCriterionRead], status_code=status.HTTP_201_CREATED)
async def parse_trial_criteria(
    trial_id: UUID,
    _: Annotated[User, Depends(require_role(UserRole.owner, UserRole.pi, UserRole.coordinator))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TrialCriterionRead]:
    await _get_trial_or_404(db, trial_id)

    latest_doc_result = await db.execute(
        select(TrialDocument).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    latest_doc = latest_doc_result.scalars().first()
    if latest_doc is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No protocol document uploaded")

    contents, _ = await storage_download_file(latest_doc.file_path)
    tmp_path = get_local_path_for_extraction(latest_doc.file_path, contents)
    text = extract_text(tmp_path)

    if not text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Could not extract text from document")

    parsed = await parse_criteria_from_text(text)
    if not parsed:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="No criteria detected in document")

    await db.execute(
        delete(TrialCriteria).where(
            TrialCriteria.trial_id == trial_id,
            TrialCriteria.document_version == latest_doc.version,
        )
    )

    rows: list[TrialCriteria] = []
    for item in parsed:
        item_type = item.get("type", "inclusion")
        type_value = CriteriaType.exclusion if item_type == "exclusion" else CriteriaType.inclusion
        text_value = str(item.get("text", "")).strip()
        if not text_value:
            continue
        confidence_value = ConfidenceLevel.high if item.get("confidence") == "high" else ConfidenceLevel.needs_review
        expression_value = item.get("expression")
        manual_review_required = confidence_value == ConfidenceLevel.needs_review

        try:
            validate_expression(expression_value)
            expression_payload = expression_value
        except Exception:
            expression_payload = {"op": "is_true", "field": "manual_review_placeholder"}
            confidence_value = ConfidenceLevel.needs_review
            manual_review_required = True

        row = TrialCriteria(
            trial_id=trial_id,
            document_version=latest_doc.version,
            type=type_value,
            text=text_value,
            expression=expression_payload,
            confidence=confidence_value,
            manual_review_required=manual_review_required,
            approved_by=None,
            approved_at=None,
            rule_version=ENGINE_RULE_VERSION,
        )
        db.add(row)
        rows.append(row)

    await db.commit()

    for row in rows:
        await db.refresh(row)

    return [TrialCriterionRead.model_validate(row) for row in rows]


@router.get("/trials/{trial_id}/criteria", response_model=list[TrialCriterionRead])
async def list_trial_criteria(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[TrialCriterionRead]:
    await _get_trial_or_404(db, trial_id)
    result = await db.execute(
        select(TrialCriteria).where(TrialCriteria.trial_id == trial_id).order_by(TrialCriteria.document_version.desc())
    )
    return [TrialCriterionRead.model_validate(item) for item in result.scalars().all()]


@router.patch("/trials/{trial_id}/criteria/{criterion_id}", response_model=TrialCriterionRead)
async def patch_trial_criterion(
    trial_id: UUID,
    criterion_id: UUID,
    payload: TrialCriterionUpdate,
    user: Annotated[User, Depends(require_role(UserRole.owner, UserRole.pi, UserRole.coordinator))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialCriterionRead:
    criterion = await _get_criterion_or_404(db, trial_id, criterion_id)

    changed = False
    if payload.text is not None:
        criterion.text = payload.text
        changed = True

    if payload.expression is not None:
        try:
            validate_expression(payload.expression)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Invalid expression payload: {exc}",
            )
        criterion.expression = payload.expression
        changed = True

    if payload.manual_review_required is not None:
        criterion.manual_review_required = payload.manual_review_required
        changed = True

    if changed:
        criterion.approved_by = None
        criterion.approved_at = None

    if payload.approve is True:
        criterion.approved_by = user.id
        criterion.approved_at = datetime.now(UTC)

    if payload.approve is False:
        criterion.approved_by = None
        criterion.approved_at = None

    await db.commit()
    await db.refresh(criterion)
    return TrialCriterionRead.model_validate(criterion)


@router.post("/trials/{trial_id}/criteria/{criterion_id}/approve", response_model=TrialCriterionRead)
async def approve_criterion(
    trial_id: UUID,
    criterion_id: UUID,
    user: Annotated[User, Depends(require_role(UserRole.owner, UserRole.pi, UserRole.coordinator))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> TrialCriterionRead:
    criterion = await _get_criterion_or_404(db, trial_id, criterion_id)
    criterion.approved_by = user.id
    criterion.approved_at = datetime.now(UTC)

    await db.commit()
    await db.refresh(criterion)
    return TrialCriterionRead.model_validate(criterion)


@router.post("/trials/{trial_id}/criteria/approve-all")
async def approve_all_high_confidence(
    trial_id: UUID,
    user: Annotated[User, Depends(require_role(UserRole.owner, UserRole.pi, UserRole.coordinator))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    await _get_trial_or_404(db, trial_id)

    result = await db.execute(
        select(TrialCriteria).where(
            TrialCriteria.trial_id == trial_id,
            TrialCriteria.confidence == ConfidenceLevel.high,
            TrialCriteria.approved_at.is_(None),
            TrialCriteria.manual_review_required.is_(False),
        )
    )
    rows = result.scalars().all()

    now = datetime.now(UTC)
    for row in rows:
        row.approved_by = user.id
        row.approved_at = now

    await db.commit()
    return {"approved_count": len(rows)}


@router.get("/trials/{trial_id}/criteria/review-status", response_model=CriteriaReviewStatusRead)
async def criteria_review_status(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CriteriaReviewStatusRead:
    await _get_trial_or_404(db, trial_id)

    result = await db.execute(select(TrialCriteria).where(TrialCriteria.trial_id == trial_id))
    rows = result.scalars().all()

    return CriteriaReviewStatusRead(
        total=len(rows),
        approved=sum(1 for item in rows if item.approved_at is not None),
        needs_review=sum(1 for item in rows if item.confidence == ConfidenceLevel.needs_review),
        blocking_count=sum(
            1
            for item in rows
            if item.approved_at is None
            and item.confidence == ConfidenceLevel.needs_review
            and not item.manual_review_required
        ),
    )
