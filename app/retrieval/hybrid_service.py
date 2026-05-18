from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.indexing import search_vector_chunks
from app.models import Chunk, PropertyRecord, SourceDocument


@dataclass(frozen=True)
class HybridChunkMatch:
    property_record: PropertyRecord
    source_document: SourceDocument
    chunk: Chunk
    matched_terms: list[str]
    relevance_score: Decimal
    selection_reason: str


def _dedupe_key(property_record: PropertyRecord) -> str:
    return property_record.duplicate_group_key or property_record.normalized_address or str(property_record.id)


def _matched_terms(chunk_text: str, expanded_terms: list[str]) -> list[str]:
    normalized_chunk = chunk_text.lower()
    return [term for term in expanded_terms if term in normalized_chunk]


def _rank_tuple(match_count: int, property_record: PropertyRecord) -> tuple[int, float, float, str]:
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    return (match_count, authority, freshness, property_record.address or "")


def _relevance_score(match_count: int, property_record: PropertyRecord) -> Decimal:
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    raw_score = 0.45 + (0.12 * match_count) + (0.15 * authority) + (0.08 * freshness)
    bounded = max(0.0500, min(0.9999, raw_score))
    return Decimal(f"{bounded:.4f}")


async def retrieve_loading_access_matches(
    session: AsyncSession,
    *,
    property_type: str,
    expanded_terms: list[str],
) -> list[HybridChunkMatch]:
    vector_query = f"{property_type} listings with " + " or ".join(expanded_terms[:4])
    vector_matches = await search_vector_chunks(
        vector_query,
        property_type=property_type,
        terms=expanded_terms,
        limit=10,
        candidate_limit=30,
    )
    if vector_matches:
        deduped_vector: dict[str, HybridChunkMatch] = {}
        for vector_match in vector_matches:
            if vector_match.property_record is None:
                continue
            matched_terms = _matched_terms(vector_match.chunk.chunk_text, expanded_terms)
            if not matched_terms:
                continue
            selection_reason = vector_match.selection_reason
            if vector_match.rerank_score is not None:
                selection_reason = f"{selection_reason} ({vector_match.rerank_score:.3f})"
            candidate = HybridChunkMatch(
                property_record=vector_match.property_record,
                source_document=vector_match.source_document,
                chunk=vector_match.chunk,
                matched_terms=matched_terms,
                relevance_score=vector_match.relevance_score,
                selection_reason=selection_reason,
            )
            key = _dedupe_key(vector_match.property_record)
            existing = deduped_vector.get(key)
            if existing is None or float(candidate.relevance_score) > float(existing.relevance_score):
                deduped_vector[key] = candidate
        if deduped_vector:
            return sorted(deduped_vector.values(), key=lambda item: float(item.relevance_score), reverse=True)

    ilike_filters = [Chunk.chunk_text.ilike(f"%{term}%") for term in expanded_terms]
    statement = (
        select(PropertyRecord, SourceDocument, Chunk)
        .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
        .join(Chunk, PropertyRecord.chunk_id == Chunk.id)
        .where(PropertyRecord.property_type == property_type)
        .where(or_(*ilike_filters))
    )
    rows = await session.execute(statement)

    deduped: dict[str, HybridChunkMatch] = {}
    for property_record, source_document, chunk in rows:
        matched_terms = _matched_terms(chunk.chunk_text, expanded_terms)
        if not matched_terms:
            continue

        choice_reason = f"keyword fallback matched: {', '.join(matched_terms)}"
        candidate = HybridChunkMatch(
            property_record=property_record,
            source_document=source_document,
            chunk=chunk,
            matched_terms=matched_terms,
            relevance_score=_relevance_score(len(matched_terms), property_record),
            selection_reason=choice_reason,
        )
        key = _dedupe_key(property_record)
        existing = deduped.get(key)
        if existing is None or _rank_tuple(len(matched_terms), property_record) > _rank_tuple(
            len(existing.matched_terms),
            existing.property_record,
        ):
            deduped[key] = candidate

    return sorted(
        deduped.values(),
        key=lambda item: _rank_tuple(len(item.matched_terms), item.property_record),
        reverse=True,
    )


__all__ = ["HybridChunkMatch", "retrieve_loading_access_matches"]