import logging
import re
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import delete, select

from app.config import get_settings
from app.database import AsyncSessionLocal
from app.models.enums import JobStatus
from app.models.trial import BackgroundJob, ProtocolEmbedding
from app.services.documents import extract_text

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:
    AsyncOpenAI = None

logger = logging.getLogger(__name__)
settings = get_settings()
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")
TOKEN_PATTERN = re.compile(r"\S+")


def _redis_settings_from_dsn(dsn: str) -> RedisSettings:
    parsed = urlparse(dsn)
    db = int((parsed.path or "/0").replace("/", "") or "0")
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=db,
        password=parsed.password,
    )


async def parse_trial_document(ctx: dict, job_id: str) -> None:
    del ctx
    try:
        job_uuid = UUID(job_id)
    except ValueError:
        logger.error("Invalid background job id", extra={"job_id": job_id})
        return

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(BackgroundJob).where(BackgroundJob.id == job_uuid))
        job = result.scalar_one_or_none()
        if job is None:
            logger.error("Background job not found", extra={"job_id": job_id})
            return

        try:
            job.status = JobStatus.running
            await session.commit()

            job.status = JobStatus.completed
            job.completed_at = datetime.now(UTC)
            await session.commit()
        except Exception as exc:
            job.status = JobStatus.failed
            job.error = str(exc)
            job.completed_at = datetime.now(UTC)
            await session.commit()
            logger.exception("Background job failed", extra={"job_id": job_id})


def _split_long_sentence(sentence: str, target_tokens: int) -> list[str]:
    tokens = TOKEN_PATTERN.findall(sentence)
    if not tokens:
        return []
    if len(tokens) <= target_tokens:
        return [sentence.strip()]
    return [" ".join(tokens[i : i + target_tokens]) for i in range(0, len(tokens), target_tokens)]


def _sentence_chunks(text: str, target_tokens: int = 500, overlap_tokens: int = 50) -> list[str]:
    if not text or not text.strip():
        return []

    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", normalized) if part.strip()]

    sentences: list[str] = []
    for paragraph in paragraphs:
        condensed = re.sub(r"\s+", " ", paragraph).strip()
        if not condensed:
            continue
        for raw_sentence in SENTENCE_SPLIT_PATTERN.split(condensed):
            sentence = raw_sentence.strip()
            if not sentence:
                continue
            sentences.extend(_split_long_sentence(sentence, target_tokens))

    if not sentences:
        return []

    sentence_token_counts = [len(TOKEN_PATTERN.findall(sentence)) for sentence in sentences]
    chunks: list[str] = []
    start = 0

    while start < len(sentences):
        end = start
        token_count = 0
        while end < len(sentences):
            sentence_tokens = sentence_token_counts[end]
            if token_count + sentence_tokens > target_tokens and end > start:
                break
            token_count += sentence_tokens
            end += 1

        chunk_text = " ".join(sentences[start:end]).strip()
        if chunk_text:
            chunks.append(chunk_text)

        if end >= len(sentences):
            break

        next_start = end
        overlap = 0
        while next_start > start and overlap < overlap_tokens:
            next_start -= 1
            overlap += sentence_token_counts[next_start]
        if next_start <= start:
            next_start = start + 1
        start = next_start

    return chunks


async def embed_protocol_document(ctx: dict, trial_id: str, document_version: int, file_path: str) -> None:
    del ctx

    try:
        trial_uuid = UUID(str(trial_id))
    except ValueError:
        logger.error("Invalid trial id for embedding task", extra={"trial_id": trial_id, "document_version": document_version})
        return

    if not settings.openai_api_key:
        logger.warning(
            "OPENAI_API_KEY missing; skipping protocol embedding",
            extra={"trial_id": trial_id, "document_version": document_version},
        )
        return
    if AsyncOpenAI is None:
        logger.warning(
            "openai package missing; skipping protocol embedding",
            extra={"trial_id": trial_id, "document_version": document_version},
        )
        return

    text = extract_text(file_path)
    chunks = _sentence_chunks(text=text, target_tokens=500, overlap_tokens=50)

    if not chunks:
        logger.warning(
            "No extractable text found for protocol embedding",
            extra={"trial_id": trial_id, "document_version": document_version, "file_path": file_path},
        )

    client = AsyncOpenAI(api_key=settings.openai_api_key)

    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(ProtocolEmbedding).where(
                ProtocolEmbedding.trial_id == trial_uuid,
                ProtocolEmbedding.document_version == document_version,
            )
        )

        for chunk_index, chunk_text in enumerate(chunks):
            try:
                embedding_response = await client.embeddings.create(
                    model=settings.embedding_model,
                    input=chunk_text,
                )
            except Exception:
                logger.exception(
                    "Failed to generate chunk embedding",
                    extra={
                        "trial_id": trial_id,
                        "document_version": document_version,
                        "chunk_index": chunk_index,
                    },
                )
                continue

            vector = embedding_response.data[0].embedding
            session.add(
                ProtocolEmbedding(
                    trial_id=trial_uuid,
                    document_version=document_version,
                    chunk_text=chunk_text,
                    embedding=vector,
                    chunk_index=chunk_index,
                )
            )

        await session.commit()


class WorkerSettings:
    functions = [parse_trial_document, embed_protocol_document]
    redis_settings = _redis_settings_from_dsn(settings.redis_url)
