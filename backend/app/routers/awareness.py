from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.deps import get_current_user
from app.models.trial import Trial
from app.models.user import User
from app.schemas.awareness import AwarenessCardGenerateRequest, AwarenessCardResponse
from app.services.awareness_card import build_awareness_card

router = APIRouter(prefix="/trials", tags=["awareness"])


@router.post("/{trial_id}/awareness/generate", response_model=AwarenessCardResponse)
async def generate_awareness_card(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    payload: AwarenessCardGenerateRequest | None = None,
) -> AwarenessCardResponse:
    result = await db.execute(select(Trial).where(Trial.id == trial_id))
    trial = result.scalar_one_or_none()
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")

    overrides = payload or AwarenessCardGenerateRequest()
    return await build_awareness_card(trial, overrides)
