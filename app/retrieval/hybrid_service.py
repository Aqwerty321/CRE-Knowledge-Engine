from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.indexing import rerank_documents, search_vector_chunks
from app.models import Chunk, PropertyRecord, SourceDocument
from app.retrieval.hybrid_pipeline import LocalHybridRetrievalPipeline
from app.retrieval.retrieval_config import load_hybrid_retrieval_config
from app.retrieval.retrieval_types import FusedCandidate, RetrievalDocument, RetrievalHit
from app.retrieval.text_utils import matched_terms_in_text


@dataclass(frozen=True)
class HybridChunkMatch:
    property_record: PropertyRecord
    source_document: SourceDocument
    chunk: Chunk
    matched_terms: list[str]
    relevance_score: Decimal
    selection_reason: str
    retrieval_metadata: dict[str, object] = field(default_factory=dict)


def _dedupe_key(property_record: PropertyRecord) -> str:
    return property_record.duplicate_group_key or property_record.normalized_address or str(property_record.id)


def _matched_terms(chunk_text: str, expanded_terms: list[str]) -> list[str]:
    return list(matched_terms_in_text(chunk_text, expanded_terms))


def _rank_tuple(score: float, match_count: int, property_record: PropertyRecord) -> tuple[float, int, float, float, str]:
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    return (score, match_count, authority, freshness, property_record.address or "")


def _relevance_score(fused_score: float, match_count: int, property_record: PropertyRecord) -> Decimal:
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    raw_score = 0.35 + (0.35 * fused_score) + (0.08 * match_count) + (0.14 * authority) + (0.08 * freshness)
    bounded = max(0.0500, min(0.9999, raw_score))
    return Decimal(f"{bounded:.4f}")


def _candidate_document_id(chunk: Chunk, property_record: PropertyRecord) -> str:
    return f"{chunk.id}:{property_record.id}"


def _candidate_from_document_id(document_id: str) -> tuple[UUID, UUID] | None:
    chunk_id, separator, property_record_id = document_id.partition(":")
    if not separator:
        return None
    try:
        return UUID(chunk_id), UUID(property_record_id)
    except ValueError:
        return None


def _contribution_summary(candidate: FusedCandidate) -> str:
    pieces = [f"{item.retriever}#{item.rank}" for item in candidate.contributions[:5]]
    return ", ".join(pieces) if pieces else "local retrieval"


async def _candidate_rows(
    session: AsyncSession,
    *,
    property_type: str,
) -> list[tuple[PropertyRecord, SourceDocument, Chunk]]:
    result = await session.execute(
        select(PropertyRecord, SourceDocument, Chunk)
        .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
        .join(Chunk, PropertyRecord.chunk_id == Chunk.id)
        .where(PropertyRecord.property_type == property_type)
        .order_by(SourceDocument.posted_at.desc().nullslast(), Chunk.chunk_index)
    )
    return list(result.all())


def _documents_from_rows(rows: list[tuple[PropertyRecord, SourceDocument, Chunk]]) -> list[RetrievalDocument]:
    documents: list[RetrievalDocument] = []
    for property_record, source_document, chunk in rows:
        documents.append(
            RetrievalDocument(
                id=_candidate_document_id(chunk, property_record),
                text=chunk.chunk_text,
                metadata={
                    "chunk_id": str(chunk.id),
                    "property_record_id": str(property_record.id),
                    "source_document_id": str(source_document.id),
                    "address": property_record.address,
                    "duplicate_group_key": _dedupe_key(property_record),
                },
            )
        )
    return documents


async def _vector_hits(
    query_text: str,
    *,
    property_type: str,
    expanded_terms: list[str],
    document_ids: set[str],
    candidate_limit: int,
) -> list[RetrievalHit]:
    if not get_settings().vector_search_enabled:
        return []

    vector_matches = await search_vector_chunks(
        query_text,
        property_type=property_type,
        terms=expanded_terms,
        limit=candidate_limit,
        candidate_limit=max(candidate_limit, 30),
    )
    hits: list[RetrievalHit] = []
    for rank, vector_match in enumerate(vector_matches, start=1):
        if vector_match.property_record is None:
            continue
        document_id = _candidate_document_id(vector_match.chunk, vector_match.property_record)
        if document_id not in document_ids:
            continue
        hits.append(
            RetrievalHit(
                document_id=document_id,
                retriever="qdrant_vector",
                rank=rank,
                score=float(vector_match.relevance_score),
                matched_terms=tuple(vector_match.matched_terms),
                metadata={
                    "vector_score": vector_match.vector_score,
                    "rerank_score": vector_match.rerank_score,
                    "selection_reason": vector_match.selection_reason,
                },
            )
        )
    return hits


def _metadata_for_candidate(candidate: FusedCandidate, *, layer_status: dict[str, str], query_terms: list[str]) -> dict[str, object]:
    return {
        "retrieval_contributors": sorted({item.retriever for item in candidate.contributions}),
        "contributions": [
            {
                "retriever": item.retriever,
                "rank": item.rank,
                "score": round(item.score, 4),
                "matched_terms": list(item.matched_terms),
            }
            for item in candidate.contributions
        ],
        "layer_status": dict(layer_status),
        "query_expansion_terms": query_terms,
    }


async def retrieve_loading_access_matches(
    session: AsyncSession,
    *,
    property_type: str,
    expanded_terms: list[str],
    query_text: str | None = None,
    concept: str | None = "loading_access_or_yard_space",
) -> list[HybridChunkMatch]:
    query = query_text or f"{property_type} listings with " + " or ".join(expanded_terms[:4])
    rows = await _candidate_rows(session, property_type=property_type)
    documents = _documents_from_rows(rows)
    if not documents:
        return []

    row_by_document_id = {
        _candidate_document_id(chunk, property_record): (property_record, source_document, chunk)
        for property_record, source_document, chunk in rows
    }
    config = load_hybrid_retrieval_config()
    pipeline = LocalHybridRetrievalPipeline(config)
    vector_hits = await _vector_hits(
        query,
        property_type=property_type,
        expanded_terms=expanded_terms,
        document_ids=set(row_by_document_id),
        candidate_limit=config.candidate_limit,
    )
    rerank_hook = rerank_documents if get_settings().vector_search_enabled else None
    pipeline_result = await pipeline.retrieve(
        query,
        documents,
        concept=concept,
        limit=config.limit,
        external_results=vector_hits,
        rerank_hook=rerank_hook,
    )

    deduped: dict[str, HybridChunkMatch] = {}
    for fused_candidate in pipeline_result.candidates:
        if _candidate_from_document_id(fused_candidate.document.id) is None:
            continue
        row = row_by_document_id.get(fused_candidate.document.id)
        if row is None:
            continue
        property_record, source_document, chunk = row
        matched_terms = list(fused_candidate.matched_terms) or _matched_terms(chunk.chunk_text, expanded_terms)
        if not matched_terms:
            continue

        choice_reason = (
            f"hybrid local retrieval matched: {', '.join(matched_terms)} "
            f"via {_contribution_summary(fused_candidate)}"
        )
        metadata = _metadata_for_candidate(
            fused_candidate,
            layer_status=pipeline_result.layer_status,
            query_terms=list(pipeline_result.expansion.expanded_terms),
        )
        candidate = HybridChunkMatch(
            property_record=property_record,
            source_document=source_document,
            chunk=chunk,
            matched_terms=matched_terms,
            relevance_score=_relevance_score(fused_candidate.score, len(matched_terms), property_record),
            selection_reason=choice_reason,
            retrieval_metadata=metadata,
        )
        key = _dedupe_key(property_record)
        existing = deduped.get(key)
        if existing is None or _rank_tuple(fused_candidate.score, len(matched_terms), property_record) > _rank_tuple(
            float(existing.relevance_score),
            len(existing.matched_terms),
            existing.property_record,
        ):
            deduped[key] = candidate

    return sorted(
        deduped.values(),
        key=lambda item: _rank_tuple(float(item.relevance_score), len(item.matched_terms), item.property_record),
        reverse=True,
    )


__all__ = ["HybridChunkMatch", "retrieve_loading_access_matches"]