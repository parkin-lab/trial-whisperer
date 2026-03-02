from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.trial import CtgSnapshot, Trial
from app.models.user import User
from app.schemas.trial import CtgSnapshotCreate, CtgSnapshotRead
from app.services.ctg import CtgServiceError, fetch_study, search_studies

router = APIRouter(tags=["ctg"])


@router.get("/ctg/search")
async def ctg_search(
    q: Annotated[str, Query(min_length=2)],
    _: Annotated[User, Depends(get_current_user)],
) -> list[dict]:
    try:
        return await search_studies(q)
    except CtgServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/trials/{trial_id}/ctg-snapshot", response_model=CtgSnapshotRead, status_code=status.HTTP_201_CREATED)
async def create_ctg_snapshot(
    trial_id: UUID,
    payload: CtgSnapshotCreate,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CtgSnapshotRead:
    result = await db.execute(select(Trial).where(Trial.id == trial_id))
    trial = result.scalar_one_or_none()
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")

    try:
        raw = await fetch_study(payload.nct_id)
    except CtgServiceError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))

    trial.nct_id = payload.nct_id
    trial.ctg_url = f"https://clinicaltrials.gov/study/{payload.nct_id}"
    snapshot = CtgSnapshot(trial_id=trial_id, nct_id=payload.nct_id, raw_json=raw)
    db.add(snapshot)
    await db.commit()
    await db.refresh(snapshot)

    return CtgSnapshotRead.model_validate(snapshot)


@router.get("/trials/{trial_id}/ctg-snapshot", response_model=CtgSnapshotRead | None)
async def get_latest_ctg_snapshot(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CtgSnapshotRead | None:
    result = await db.execute(
        select(CtgSnapshot).where(CtgSnapshot.trial_id == trial_id).order_by(CtgSnapshot.pulled_at.desc())
    )
    snapshot = result.scalars().first()
    if snapshot is None:
        return None
    return CtgSnapshotRead.model_validate(snapshot)
