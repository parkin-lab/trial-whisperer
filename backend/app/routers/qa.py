"""
Protocol Q&A using Claude via OpenClaw gateway.
Passes full protocol text as context (no embeddings/RAG needed - Claude has long context).
"""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.deps import get_current_user
from app.models.trial import Trial, TrialDocument
from app.models.user import User
from app.schemas.trial import QARequest, QAResponse
from app.services.documents import extract_text
from app.services.llm import chat_completion
from app.services.storage import download_file

router = APIRouter(tags=["qa"])
settings = get_settings()

SYSTEM_PROMPT = """You are a clinical trial protocol assistant. Answer questions about the trial protocol strictly based on the provided protocol text.

Rules:
- Only use information present in the protocol text
- If the information is not in the protocol, say so explicitly
- Quote relevant sections to support your answer
- Be precise about dosing, timing, and eligibility criteria
- Do not make assumptions or extrapolate beyond the text"""
BRIEF_MODE_INSTRUCTIONS = """For this response, return plain bullet points only.
- No markdown headers
- No code blocks
- Max 6 bullets
- One concise fact per bullet"""


def _strip_markdown_artifacts(answer: str | None) -> str:
    if not answer:
        return ""
    cleaned_lines: list[str] = []
    for raw_line in answer.splitlines():
        line = re.sub(r"^\s*(?:#{1,3}|\*\*|```+)\s*", "", raw_line)
        line = line.replace("**", "").replace("```", "")
        cleaned_lines.append(line.rstrip())
    cleaned = "\n".join(cleaned_lines).strip()
    return re.sub(r"\n{3,}", "\n\n", cleaned)


def _as_brief_bullets(answer: str) -> str:
    candidates: list[str] = []
    for line in answer.splitlines():
        text = re.sub(r"^\s*(?:[-*•]\s+|\d+[.)]\s+)", "", line).strip()
        if text:
            candidates.append(text)

    if not candidates and answer.strip():
        sentence_candidates = re.split(r"(?<=[.!?])\s+", answer.strip())
        candidates = [item.strip() for item in sentence_candidates if item.strip()]

    return "\n".join(f"- {item}" for item in candidates[:6])


async def _get_latest_protocol_text(trial_id: UUID, db: AsyncSession) -> str | None:
    """Get text content of the latest protocol document for a trial."""
    result = await db.execute(
        select(TrialDocument).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    doc = result.scalars().first()
    if doc is None:
        return None

    try:
        contents, _ = await download_file(doc.file_path)
        suffix = Path(doc.file_path).suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp.write(contents)
            temp_path = tmp.name
        try:
            return extract_text(temp_path)
        finally:
            os.unlink(temp_path)
    except Exception:
        return None


@router.post("/trials/{trial_id}/qa", response_model=QAResponse)
async def protocol_qa(
    trial_id: UUID,
    payload: QARequest,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> QAResponse:
    result = await db.execute(select(Trial).where(Trial.id == trial_id))
    trial = result.scalar_one_or_none()
    if trial is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trial not found")

    protocol_text = await _get_latest_protocol_text(trial_id, db)
    if not protocol_text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No protocol document found for this trial",
        )

    answer = await chat_completion(
        messages=[
            {
                "role": "user",
                "content": f"Protocol text:\n\n{protocol_text[:150000]}\n\n---\n\nQuestion: {payload.question}",
            }
        ],
        system=f"{SYSTEM_PROMPT}\n\n{BRIEF_MODE_INSTRUCTIONS}" if payload.mode == "brief" else SYSTEM_PROMPT,
        max_tokens=1024,
        model=settings.qa_model,
    )

    if answer is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM service unavailable - check OPENCLAW_GATEWAY_TOKEN",
        )

    cleaned_answer = _strip_markdown_artifacts(answer)
    if payload.mode == "brief":
        cleaned_answer = _as_brief_bullets(cleaned_answer)

    return QAResponse(
        answer=cleaned_answer,
        sources=[],
        embeddings_pending=False,
        model="openclaw-gateway",
    )


@router.get("/trials/{trial_id}/qa/status")
async def qa_status(
    trial_id: UUID,
    _: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    result = await db.execute(
        select(TrialDocument).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    doc = result.scalars().first()
    return {
        "embeddings_exist": False,
        "chunk_count": 0,
        "document_version": doc.version if doc else None,
        "embeddings_pending": False,
        "qa_available": doc is not None,
        "mode": "full-context",
    }
