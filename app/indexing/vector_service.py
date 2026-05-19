from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

import aiohttp
from sqlalchemy import select, update

from app.config import get_settings
from app.db.session import SessionFactory
from app.models import Chunk, PropertyRecord, SourceDocument


@dataclass(frozen=True)
class VectorChunkMatch:
    chunk: Chunk
    source_document: SourceDocument
    property_record: PropertyRecord | None
    vector_score: float
    rerank_score: float | None
    relevance_score: Decimal
    matched_terms: list[str]
    selection_reason: str


def _bounded_decimal_score(value: float) -> Decimal:
    bounded = max(0.0500, min(0.9999, value))
    return Decimal(f"{bounded:.4f}")


def _models_url(endpoint_url: str) -> str:
    if endpoint_url.endswith("/v1/embeddings"):
        return endpoint_url[: -len("/embeddings")] + "/models"
    if endpoint_url.endswith("/v1/rerank"):
        return endpoint_url[: -len("/rerank")] + "/models"
    return endpoint_url.rstrip("/") + "/v1/models"


async def _get_json(url: str, *, timeout_seconds: float = 2.0) -> tuple[int, dict[str, Any] | None]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                payload = await response.json(content_type=None)
                return response.status, payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001 - dependency checks should not raise into health routes
        return 0, None


async def check_vector_dependencies() -> dict[str, str]:
    settings = get_settings()
    checks: dict[str, str] = {
        "qdrant": "missing_config" if not settings.qdrant_url else "unavailable",
        "embedding": "disabled",
        "rerank": "disabled",
        "ocr": "disabled",
    }

    if settings.qdrant_url:
        status_code, _payload = await _get_json(f"{settings.qdrant_url.rstrip('/')}/collections")
        checks["qdrant"] = "ok" if status_code == 200 else "unavailable"

    if settings.vector_search_enabled or settings.vector_index_on_import:
        status_code, _payload = await _get_json(_models_url(settings.embedding_url))
        checks["embedding"] = "ok" if status_code == 200 else "unavailable"
        status_code, _payload = await _get_json(_models_url(settings.rerank_url))
        checks["rerank"] = "ok" if status_code == 200 else "unavailable"

    if settings.ocr_enabled:
        status_code, _payload = await _get_json(f"{settings.ocr_backend_url.rstrip('/')}/health")
        checks["ocr"] = "ok" if status_code == 200 else "unavailable"

    return checks


async def _embed_texts(texts: list[str]) -> list[list[float]]:
    settings = get_settings()
    timeout = aiohttp.ClientTimeout(total=settings.embedding_request_timeout_seconds)
    payload = {"model": settings.embedding_model, "input": texts}
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(settings.embedding_url, json=payload) as response:
            response.raise_for_status()
            body = await response.json()

    rows = sorted(body.get("data", []), key=lambda item: int(item.get("index", 0)))
    return [list(row.get("embedding") or []) for row in rows]


async def _ensure_collection() -> bool:
    settings = get_settings()
    collection_url = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}"
    timeout = aiohttp.ClientTimeout(total=10.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(collection_url) as response:
            if response.status == 200:
                return True
            if response.status not in {404, 409}:
                return False

        payload = {
            "vectors": {
                "size": settings.embedding_dimension,
                "distance": "Cosine",
            }
        }
        async with session.put(collection_url, json=payload) as response:
            return response.status in {200, 201}


async def _delete_collection() -> bool:
    settings = get_settings()
    collection_url = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}"
    timeout = aiohttp.ClientTimeout(total=10.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.delete(collection_url) as response:
            return response.status in {200, 202, 404}


async def _upsert_points(points: list[dict[str, Any]]) -> bool:
    if not points:
        return True
    settings = get_settings()
    url = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}/points?wait=true"
    timeout = aiohttp.ClientTimeout(total=30.0)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.put(url, json={"points": points}) as response:
            return response.status in {200, 202}


async def index_chunks_by_ids(chunk_ids: list[UUID]) -> dict[str, object]:
    settings = get_settings()
    if not settings.vector_index_on_import:
        return {"status": "disabled", "indexed_chunk_count": 0}
    if not chunk_ids:
        return {"status": "empty", "indexed_chunk_count": 0}
    if not await _ensure_collection():
        return {"status": "qdrant_unavailable", "indexed_chunk_count": 0}

    async with SessionFactory() as session:
        rows = list(
            (
                await session.execute(
                    select(Chunk, SourceDocument)
                    .join(SourceDocument, Chunk.document_id == SourceDocument.id)
                    .where(Chunk.id.in_(chunk_ids))
                    .order_by(Chunk.document_id, Chunk.chunk_index)
                )
            ).all()
        )
        property_rows = list(
            (
                await session.execute(
                    select(PropertyRecord)
                    .where(PropertyRecord.chunk_id.in_(chunk_ids))
                    .order_by(PropertyRecord.created_at)
                )
            ).scalars()
        )

    properties_by_chunk: dict[UUID, list[PropertyRecord]] = {}
    for property_record in property_rows:
        if property_record.chunk_id is not None:
            properties_by_chunk.setdefault(property_record.chunk_id, []).append(property_record)

    indexed_ids: list[UUID] = []
    batch_size = max(1, int(settings.embedding_batch_size))
    for start in range(0, len(rows), batch_size):
        batch = rows[start : start + batch_size]
        texts = [chunk.chunk_text for chunk, _source in batch]
        try:
            embeddings = await _embed_texts(texts)
        except Exception:  # noqa: BLE001 - indexing should not block ingestion
            continue

        points: list[dict[str, Any]] = []
        for (chunk, source_document), embedding in zip(batch, embeddings, strict=False):
            if not embedding:
                continue
            property_records = properties_by_chunk.get(chunk.id, [])
            points.append(
                {
                    "id": str(chunk.id),
                    "vector": embedding,
                    "payload": {
                        "chunk_id": str(chunk.id),
                        "document_id": str(source_document.id),
                        "source_type": source_document.source_type,
                        "file_name": source_document.file_name,
                        "slack_channel_id": source_document.slack_channel_id,
                        "slack_channel_name": source_document.slack_channel_name,
                        "posted_at": source_document.posted_at.isoformat() if source_document.posted_at else None,
                        "property_types": sorted({record.property_type for record in property_records}),
                        "addresses": sorted({record.address for record in property_records if record.address}),
                        "markets": sorted({record.market for record in property_records if record.market}),
                        "text_preview": chunk.chunk_text[:500],
                    },
                }
            )

        if await _upsert_points(points):
            indexed_ids.extend(UUID(str(point["id"])) for point in points)

    if indexed_ids:
        async with SessionFactory() as session:
            async with session.begin():
                result = await session.execute(select(Chunk).where(Chunk.id.in_(indexed_ids)))
                for chunk in result.scalars():
                    chunk.embedding_id = str(chunk.id)

    return {
        "status": "indexed" if indexed_ids else "no_vectors_indexed",
        "requested_chunk_count": len(chunk_ids),
        "indexed_chunk_count": len(indexed_ids),
        "collection": settings.qdrant_collection,
    }


async def _clear_chunk_embedding_ids() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(update(Chunk).values(embedding_id=None))


async def index_all_chunks(*, reset_collection: bool = False) -> dict[str, object]:
    settings = get_settings()
    if reset_collection and settings.vector_index_on_import:
        if not await _delete_collection():
            return {"status": "qdrant_unavailable", "indexed_chunk_count": 0, "collection": settings.qdrant_collection}
        await _clear_chunk_embedding_ids()

    async with SessionFactory() as session:
        chunk_ids = list((await session.execute(select(Chunk.id).order_by(Chunk.document_id, Chunk.chunk_index))).scalars())
    return await index_chunks_by_ids(chunk_ids)


async def _search_qdrant(query_vector: list[float], *, candidate_limit: int) -> list[dict[str, Any]]:
    settings = get_settings()
    url = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}/points/search"
    timeout = aiohttp.ClientTimeout(total=15.0)
    payload = {
        "vector": query_vector,
        "limit": candidate_limit,
        "with_payload": True,
    }
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(url, json=payload) as response:
            if response.status == 404:
                return []
            response.raise_for_status()
            body = await response.json()
    result = body.get("result")
    return list(result) if isinstance(result, list) else []


async def rerank_documents(query: str, documents: list[str]) -> dict[int, float]:
    settings = get_settings()
    if not documents:
        return {}
    timeout = aiohttp.ClientTimeout(total=settings.rerank_request_timeout_seconds)
    payload = {"model": settings.rerank_model, "query": query, "documents": documents}
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(settings.rerank_url, json=payload) as response:
                response.raise_for_status()
                body = await response.json()
    except Exception:  # noqa: BLE001 - semantic retrieval can continue with vector scores only
        return {}

    scores: dict[int, float] = {}
    for row in body.get("results", []):
        try:
            scores[int(row.get("index"))] = float(row.get("relevance_score"))
        except (TypeError, ValueError):
            continue
    return scores


def _term_hits(text: str, terms: list[str]) -> list[str]:
    normalized = text.lower()
    return [term for term in terms if term.lower() in normalized]


async def search_vector_chunks(
    query: str,
    *,
    property_type: str | None = None,
    terms: list[str] | None = None,
    limit: int = 10,
    candidate_limit: int = 30,
) -> list[VectorChunkMatch]:
    settings = get_settings()
    if not settings.vector_search_enabled:
        return []

    try:
        query_vector = (await _embed_texts([query]))[0]
        point_rows = await _search_qdrant(query_vector, candidate_limit=candidate_limit)
    except Exception:  # noqa: BLE001 - callers should fall back to keyword retrieval
        return []

    point_scores: dict[UUID, float] = {}
    for point in point_rows:
        try:
            point_scores[UUID(str(point.get("id")))] = float(point.get("score") or 0.0)
        except (TypeError, ValueError):
            continue
    if not point_scores:
        return []

    async with SessionFactory() as session:
        statement = (
            select(Chunk, SourceDocument, PropertyRecord)
            .join(SourceDocument, Chunk.document_id == SourceDocument.id)
            .outerjoin(PropertyRecord, PropertyRecord.chunk_id == Chunk.id)
            .where(Chunk.id.in_(list(point_scores)))
        )
        if property_type:
            statement = statement.where(PropertyRecord.property_type == property_type)
        rows = list((await session.execute(statement)).all())

    ordered_rows = sorted(rows, key=lambda row: point_scores.get(row[0].id, 0.0), reverse=True)
    documents = [row[0].chunk_text[:3000] for row in ordered_rows]
    rerank_scores = await rerank_documents(query, documents)

    matches: list[VectorChunkMatch] = []
    for index, (chunk, source_document, property_record) in enumerate(ordered_rows):
        vector_score = point_scores.get(chunk.id, 0.0)
        rerank_score = rerank_scores.get(index)
        combined = (0.35 * vector_score) + (0.65 * rerank_score) if rerank_score is not None else vector_score
        hits = _term_hits(chunk.chunk_text, terms or [])
        matches.append(
            VectorChunkMatch(
                chunk=chunk,
                source_document=source_document,
                property_record=property_record,
                vector_score=vector_score,
                rerank_score=rerank_score,
                relevance_score=_bounded_decimal_score(combined),
                matched_terms=hits or ["semantic match"],
                selection_reason=(
                    "qdrant vector search + local reranker"
                    if rerank_score is not None
                    else "qdrant vector search"
                ),
            )
        )

    matches.sort(key=lambda item: (float(item.relevance_score), item.vector_score), reverse=True)
    return matches[:limit]


__all__ = [
    "VectorChunkMatch",
    "check_vector_dependencies",
    "index_all_chunks",
    "index_chunks_by_ids",
    "rerank_documents",
    "search_vector_chunks",
]