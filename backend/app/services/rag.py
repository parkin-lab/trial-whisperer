import logging
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models.trial import ProtocolEmbedding, TrialDocument

try:
    from openai import AsyncOpenAI
except ModuleNotFoundError:
    AsyncOpenAI = None

logger = logging.getLogger(__name__)
settings = get_settings()


class ChunkResult(BaseModel):
    chunk_text: str
    chunk_index: int
    similarity: float
    document_version: int


class SearchProtocolResult(BaseModel):
    chunks: list[ChunkResult]
    embeddings_pending: bool = False


class EmbeddingStatus(BaseModel):
    embeddings_exist: bool
    chunk_count: int
    document_version: int | None
    embeddings_pending: bool


class MissingOpenAIKeyError(RuntimeError):
    pass


class MissingOpenAIDependencyError(RuntimeError):
    pass


async def _resolve_document_version(
    trial_id: UUID,
    document_version: int | None,
    db: AsyncSession,
) -> int | None:
    if document_version is not None:
        return document_version

    result = await db.execute(
        select(TrialDocument.version).where(TrialDocument.trial_id == trial_id).order_by(TrialDocument.version.desc())
    )
    latest_version = result.scalars().first()
    return latest_version


async def get_embedding_status(
    trial_id: str,
    db: AsyncSession,
) -> EmbeddingStatus:
    trial_uuid = UUID(str(trial_id))
    target_version = await _resolve_document_version(trial_uuid, None, db)

    if target_version is None:
        return EmbeddingStatus(
            embeddings_exist=False,
            chunk_count=0,
            document_version=None,
            embeddings_pending=False,
        )

    count_result = await db.execute(
        select(func.count(ProtocolEmbedding.id)).where(
            ProtocolEmbedding.trial_id == trial_uuid,
            ProtocolEmbedding.document_version == target_version,
        )
    )
    chunk_count = int(count_result.scalar() or 0)
    embeddings_exist = chunk_count > 0

    return EmbeddingStatus(
        embeddings_exist=embeddings_exist,
        chunk_count=chunk_count,
        document_version=target_version,
        embeddings_pending=not embeddings_exist,
    )


async def search_protocol(
    trial_id: str,
    query: str,
    document_version: int | None,
    db: AsyncSession,
    top_k: int = 5,
) -> SearchProtocolResult:
    """
    1. Embed the query using OpenAI text-embedding-3-small
    2. Run pgvector cosine similarity search against protocol_embeddings for this trial
    3. Return top_k chunks sorted by similarity, with chunk_index for ordering
    """
    trial_uuid = UUID(str(trial_id))
    target_version = await _resolve_document_version(trial_uuid, document_version, db)

    if target_version is None:
        return SearchProtocolResult(chunks=[], embeddings_pending=False)

    count_result = await db.execute(
        select(func.count(ProtocolEmbedding.id)).where(
            ProtocolEmbedding.trial_id == trial_uuid,
            ProtocolEmbedding.document_version == target_version,
        )
    )
    chunk_count = int(count_result.scalar() or 0)
    if chunk_count == 0:
        return SearchProtocolResult(chunks=[], embeddings_pending=True)

    if not settings.openai_api_key:
        raise MissingOpenAIKeyError("OPENAI_API_KEY is not configured")
    if AsyncOpenAI is None:
        raise MissingOpenAIDependencyError("openai package is not installed")

    client = AsyncOpenAI(api_key=settings.openai_api_key)
    embedding_response = await client.embeddings.create(
        model="text-embedding-3-small",
        input=query,
    )
    query_embedding = embedding_response.data[0].embedding

    distance = ProtocolEmbedding.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            ProtocolEmbedding.chunk_text,
            ProtocolEmbedding.chunk_index,
            ProtocolEmbedding.document_version,
            (1 - distance).label("similarity"),
        )
        .where(
            ProtocolEmbedding.trial_id == trial_uuid,
            ProtocolEmbedding.document_version == target_version,
        )
        .order_by(distance.asc(), ProtocolEmbedding.chunk_index.asc())
        .limit(top_k)
    )
    rows = (await db.execute(stmt)).all()

    chunks = [
        ChunkResult(
            chunk_text=row.chunk_text,
            chunk_index=row.chunk_index,
            similarity=float(row.similarity),
            document_version=row.document_version,
        )
        for row in rows
    ]
    return SearchProtocolResult(chunks=chunks, embeddings_pending=False)
