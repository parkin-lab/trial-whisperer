import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.trial import Trial
from app.models.user import User
from app.services.rag import (
    ChunkResult,
    EmbeddingStatus,
    MissingOpenAIDependencyError,
    MissingOpenAIKeyError,
    SearchProtocolResult,
    get_embedding_status,
    search_protocol,
)

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:
    AsyncOpenAI = None

router = APIRouter(tags=["qa"])
settings = get_settings()
logger = logging.getLogger(__name__)


class QARequest(BaseModel):
    question: str = Field(min_length=1, max_length=5000)
    document_version: int | None = None

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Question cannot be empty")
        return cleaned


class QAResponse(BaseModel):
    answer: str | None
    sources: list[ChunkResult]
    embeddings_pending: bool
    model: str


async def _ensure_trial_exists(db: AsyncSession, trial_id: UUID) -> None:
    result = await db.execute(select(Trial.id).where(Trial.id == trial_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")


@router.get("/trials/{trial_id}/qa/status", response_model=EmbeddingStatus)
async def protocol_qa_status(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> EmbeddingStatus:
    await _ensure_trial_exists(db, trial_id)
    return await get_embedding_status(str(trial_id), db)


@router.post("/trials/{trial_id}/qa", response_model=QAResponse)
async def protocol_qa(
    trial_id: UUID,
    payload: QARequest,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QAResponse:
    await _ensure_trial_exists(db, trial_id)

    if not settings.openai_api_key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured. Protocol Q&A is unavailable.",
        )

    try:
        search_result: SearchProtocolResult = await search_protocol(
            trial_id=str(trial_id),
            query=payload.question,
            document_version=payload.document_version,
            top_k=5,
            db=db,
        )
    except MissingOpenAIKeyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="OPENAI_API_KEY is not configured. Protocol Q&A is unavailable.",
        )
    except MissingOpenAIDependencyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="openai package is not installed. Protocol Q&A is unavailable.",
        )
    except Exception:
        logger.exception("Protocol similarity search failed", extra={"trial_id": str(trial_id)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Protocol search failed. Please try again.",
        )

    if search_result.embeddings_pending:
        return QAResponse(
            answer=None,
            sources=[],
            embeddings_pending=True,
            model=settings.qa_model,
        )

    chunks = search_result.chunks
    if not chunks:
        return QAResponse(
            answer="The information is not present in the indexed protocol excerpts.",
            sources=[],
            embeddings_pending=False,
            model=settings.qa_model,
        )

    excerpts = "\n\n".join(f"[{idx}] {chunk.chunk_text}" for idx, chunk in enumerate(chunks, start=1))
    messages = [
        {
            "role": "system",
            "content": (
                "You are a clinical trial protocol assistant. Answer questions about the trial protocol strictly "
                "based on the provided excerpts. Do not invent information not present in the excerpts. "
                "Always cite which excerpt supports your answer."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Protocol excerpts:\n{excerpts}\n\n"
                f"Question: {payload.question}\n\n"
                "Answer based only on the excerpts above. If the information is not present, say so explicitly."
            ),
        },
    ]

    try:
        if AsyncOpenAI is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="openai package is not installed. Protocol Q&A is unavailable.",
            )
        client = AsyncOpenAI(api_key=settings.openai_api_key)
        completion = await client.chat.completions.create(
            model=settings.qa_model,
            messages=messages,
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("Protocol QA completion failed", extra={"trial_id": str(trial_id)})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Protocol Q&A completion failed. Please try again.",
        )

    answer_text = (completion.choices[0].message.content or "").strip()
    if not answer_text:
        answer_text = "The information is not present in the indexed protocol excerpts."

    return QAResponse(
        answer=answer_text,
        sources=chunks,
        embeddings_pending=False,
        model=settings.qa_model,
    )
