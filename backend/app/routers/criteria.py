from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user, require_role
from app.engine.schema import validate_expression
from app.models.enums import ConfidenceLevel, CriteriaParseStatus, CriteriaType, UserRole
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


def _normalize_parse_payload(item_expression: dict | None, item_confidence: ConfidenceLevel, item_parse_status: CriteriaParseStatus | None) -> tuple[dict | None, ConfidenceLevel, bool, CriteriaParseStatus]:
    expression_payload = item_expression
    confidence_value = item_confidence
    manual_review_required = expression_payload is None
    parse_status = item_parse_status or CriteriaParseStatus.needs_review

    if expression_payload is None:
        return None, ConfidenceLevel.needs_review, True, CriteriaParseStatus.needs_review

    try:
        validate_expression(expression_payload)
    except Exception:
        return None, ConfidenceLevel.needs_review, True, CriteriaParseStatus.needs_review

    if parse_status == CriteriaParseStatus.needs_review and confidence_value == ConfidenceLevel.high:
        parse_status = CriteriaParseStatus.parsed
    return expression_payload, confidence_value, manual_review_required, parse_status


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

    await db.execute(
        delete(TrialCriteria).where(
            TrialCriteria.trial_id == trial_id,
            TrialCriteria.document_version == latest_doc.version,
        )
    )

    rows: list[TrialCriteria] = []
    for item in parsed:
        if not (item.text or "").strip():
            continue

        expression_payload, confidence_value, manual_review_required, parse_status = _normalize_parse_payload(
            item.expression,
            item.confidence,
            item.parse_status,
        )

        row = TrialCriteria(
            trial_id=trial_id,
            document_version=latest_doc.version,
            type=item.type,
            text=item.text,
            expression=expression_payload,
            confidence=confidence_value,
            manual_review_required=manual_review_required or item.manual_review_required,
            source_order=item.source_order,
            section_label=item.section_label,
            parse_status=parse_status,
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
    criteria_type: Annotated[Literal["inclusion", "exclusion", "all"], Query(alias="type")] = "all",
) -> list[TrialCriterionRead]:
    await _get_trial_or_404(db, trial_id)
    query = select(TrialCriteria).where(TrialCriteria.trial_id == trial_id)
    if criteria_type != "all":
        query = query.where(TrialCriteria.type == CriteriaType(criteria_type))
    query = query.order_by(
        TrialCriteria.document_version.desc(),
        TrialCriteria.source_order.asc(),
        TrialCriteria.id.asc(),
    )
    result = await db.execute(query)
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
    updates = payload.model_dump(exclude_unset=True)

    content_changed = False
    if "text" in updates:
        text_value = (updates["text"] or "").strip()
        if not text_value:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="text is required")
        criterion.text = updates["text"]
        content_changed = True

    if "expression" in updates:
        expression_value = updates["expression"]
        if expression_value is not None:
            try:
                validate_expression(expression_value)
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Invalid expression payload: {exc}",
                ) from exc
        criterion.expression = expression_value
        content_changed = True

    if "confidence" in updates:
        criterion.confidence = updates["confidence"]
        content_changed = True

    if "manual_review_required" in updates:
        criterion.manual_review_required = updates["manual_review_required"]
        content_changed = True

    if content_changed:
        criterion.approved_by = None
        criterion.approved_at = None
        if "parse_status" not in updates:
            criterion.parse_status = CriteriaParseStatus.needs_review

    if "parse_status" in updates:
        parse_status = updates["parse_status"]
        criterion.parse_status = parse_status
        if parse_status == CriteriaParseStatus.approved:
            criterion.approved_by = user.id
            criterion.approved_at = datetime.now(UTC)
        else:
            criterion.approved_by = None
            criterion.approved_at = None

    if updates.get("approve") is True:
        criterion.parse_status = CriteriaParseStatus.approved
        criterion.approved_by = user.id
        criterion.approved_at = datetime.now(UTC)
    if updates.get("approve") is False:
        criterion.approved_by = None
        criterion.approved_at = None
        if criterion.parse_status == CriteriaParseStatus.approved:
            criterion.parse_status = CriteriaParseStatus.needs_review

    if criterion.parse_status == CriteriaParseStatus.parsed and criterion.expression is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="parse_status 'parsed' requires a non-null expression",
        )

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
    criterion.parse_status = CriteriaParseStatus.approved

    await db.commit()
    await db.refresh(criterion)
    return TrialCriterionRead.model_validate(criterion)


@router.delete("/trials/{trial_id}/criteria/{criterion_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_criterion(
    trial_id: UUID,
    criterion_id: UUID,
    _: Annotated[User, Depends(require_role(UserRole.owner, UserRole.pi, UserRole.coordinator))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    criterion = await _get_criterion_or_404(db, trial_id, criterion_id)
    await db.delete(criterion)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/trials/{trial_id}/criteria/approve-reviewed")
async def approve_reviewed_criteria(
    trial_id: UUID,
    user: Annotated[User, Depends(require_role(UserRole.owner, UserRole.pi, UserRole.coordinator))],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict[str, int]:
    await _get_trial_or_404(db, trial_id)

    result = await db.execute(
        select(TrialCriteria).where(
            TrialCriteria.trial_id == trial_id,
            TrialCriteria.approved_at.is_(None),
            TrialCriteria.parse_status.in_([CriteriaParseStatus.parsed, CriteriaParseStatus.manual_only]),
        )
    )
    rows = [row for row in result.scalars().all() if (row.text or "").strip()]

    now = datetime.now(UTC)
    for row in rows:
        row.approved_by = user.id
        row.approved_at = now
        row.parse_status = CriteriaParseStatus.approved

    await db.commit()
    return {"approved_count": len(rows)}


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
        row.parse_status = CriteriaParseStatus.approved

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
