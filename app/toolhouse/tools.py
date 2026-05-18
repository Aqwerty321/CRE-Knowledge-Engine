from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select

from app.answering.query_service import explain_query
from app.db.session import SessionFactory
from app.indexing import search_vector_chunks
from app.models import Chunk, PropertyRecord, SourceDocument
from app.retrieval import build_property_query, collect_data_quality_report, describe_query_constructor, retrieve_structured_property_matches
from app.toolhouse.local_agent import build_escalation_payload, run_local_deeper_review


def _serialize_decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _serialize_source_document(source_document: SourceDocument | None) -> dict[str, object] | None:
    if source_document is None:
        return None
    return {
        "id": str(source_document.id),
        "source_type": source_document.source_type,
        "file_name": source_document.file_name,
        "source_url": source_document.source_url,
        "slack_channel_name": source_document.slack_channel_name,
        "slack_user_name": source_document.slack_user_name,
        "slack_ts": source_document.slack_ts,
        "posted_at": source_document.posted_at.isoformat() if source_document.posted_at else None,
    }


def _serialize_property_record(property_record: PropertyRecord | None) -> dict[str, object] | None:
    if property_record is None:
        return None
    return {
        "id": str(property_record.id),
        "address": property_record.address,
        "normalized_address": property_record.normalized_address,
        "property_type": property_record.property_type,
        "sq_ft": property_record.sq_ft,
        "price_per_sq_ft": _serialize_decimal(property_record.price_per_sq_ft),
        "price_basis": property_record.price_basis,
        "availability": property_record.availability,
        "availability_date": property_record.availability_date.isoformat() if property_record.availability_date else None,
        "market": property_record.market,
        "geo_lat": _serialize_decimal(property_record.geo_lat),
        "geo_lng": _serialize_decimal(property_record.geo_lng),
        "source_page": property_record.source_page,
        "source_row": property_record.source_row,
        "extraction_method": property_record.extraction_method,
        "confidence": _serialize_decimal(property_record.confidence),
        "source_authority_score": _serialize_decimal(property_record.source_authority_score),
        "freshness_score": _serialize_decimal(property_record.freshness_score),
        "duplicate_group_key": property_record.duplicate_group_key,
    }


def _serialize_chunk(chunk: Chunk | None) -> dict[str, object] | None:
    if chunk is None:
        return None
    return {
        "id": str(chunk.id),
        "chunk_index": chunk.chunk_index,
        "page_number": chunk.page_number,
        "row_number": chunk.row_number,
        "section_name": chunk.section_name,
        "text_preview": chunk.chunk_text[:500],
    }


def _property_priority(property_record: PropertyRecord, source_document: SourceDocument) -> tuple[float, float, float, str]:
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    posted = source_document.posted_at.timestamp() if source_document.posted_at is not None else 0.0
    return (authority, freshness, posted, property_record.address or "")


def _dedupe_property_rows(
    rows: list[tuple[PropertyRecord, SourceDocument, Chunk | None]],
) -> list[tuple[PropertyRecord, SourceDocument, Chunk | None]]:
    deduped: dict[str, tuple[PropertyRecord, SourceDocument, Chunk | None]] = {}
    for property_record, source_document, chunk in rows:
        key = property_record.duplicate_group_key or property_record.normalized_address or str(property_record.id)
        existing = deduped.get(key)
        if existing is None or _property_priority(property_record, source_document) > _property_priority(existing[0], existing[1]):
            deduped[key] = (property_record, source_document, chunk)
    return list(deduped.values())


def _serialize_supporting_result(
    property_record: PropertyRecord,
    source_document: SourceDocument,
    chunk: Chunk | None,
) -> dict[str, object]:
    return {
        "property_record": _serialize_property_record(property_record),
        "source_document": _serialize_source_document(source_document),
        "chunk": _serialize_chunk(chunk),
    }


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("?", " ").replace(",", " ").split())


def _search_terms(query: str) -> list[str]:
    normalized = _normalize_text(query)
    token_terms = [term for term in re.findall(r"[a-z0-9][a-z0-9-]{2,}", normalized) if term not in {"the", "and", "for", "with", "that"}]
    terms = [normalized, *token_terms] if len(normalized) > 2 else token_terms
    deduped: list[str] = []
    for term in terms:
        if term and term not in deduped:
            deduped.append(term)
    return deduped[:12]


def _matched_terms(text: str, terms: list[str]) -> list[str]:
    normalized = text.lower()
    return [term for term in terms if term in normalized]


def _bounded_score(raw_score: float) -> str:
    return f"{max(0.0500, min(0.9999, raw_score)):.4f}"


def _distance_miles(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_miles = 3958.7613
    lat1_radians = math.radians(lat1)
    lat2_radians = math.radians(lat2)
    lat_delta = math.radians(lat2 - lat1)
    lng_delta = math.radians(lng2 - lng1)
    haversine = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat1_radians) * math.cos(lat2_radians) * math.sin(lng_delta / 2) ** 2
    )
    return radius_miles * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _group_key_for_row(
    property_record: PropertyRecord,
    source_document: SourceDocument,
    group_by: str | None,
) -> tuple[str, str]:
    if group_by in {None, "", "none", "null"}:
        return "all", "all_matches"
    if group_by == "property_type":
        return property_record.property_type or "unknown", property_record.property_type or "unknown"
    if group_by == "market":
        return property_record.market or "unknown", property_record.market or "unknown"
    if group_by == "source_document":
        return str(source_document.id), source_document.file_name or source_document.source_type
    if group_by == "uploader":
        return source_document.slack_user_name or "unknown", source_document.slack_user_name or "unknown"
    return "all", "all_matches"


def _metric_payload(rows: list[tuple[PropertyRecord, SourceDocument, Chunk | None]], metrics: list[str]) -> dict[str, object]:
    payload: dict[str, object] = {}
    sq_ft_values = [row[0].sq_ft for row in rows if row[0].sq_ft is not None]
    price_values = [row[0].price_per_sq_ft for row in rows if row[0].price_per_sq_ft is not None]
    for metric in metrics:
        if metric == "count":
            payload[metric] = len(rows)
        elif metric == "sum_sq_ft":
            payload[metric] = sum(sq_ft_values)
        elif metric == "avg_sq_ft":
            payload[metric] = None if not sq_ft_values else round(sum(sq_ft_values) / len(sq_ft_values), 2)
        elif metric == "avg_price_per_sq_ft":
            payload[metric] = None if not price_values else _serialize_decimal(sum(price_values, Decimal("0")) / Decimal(len(price_values)))
        elif metric == "min_price_per_sq_ft":
            payload[metric] = None if not price_values else _serialize_decimal(min(price_values))
        elif metric == "max_price_per_sq_ft":
            payload[metric] = None if not price_values else _serialize_decimal(max(price_values))
    return payload


async def explain_evidence_tool(query_id: str) -> dict[str, Any]:
    escalation_payload = await build_escalation_payload(query_id)
    return {
        "tool": "explain_evidence",
        "status": escalation_payload.get("status"),
        "payload": escalation_payload,
    }


async def search_properties_tool(filters: dict[str, object]) -> dict[str, Any]:
    async with SessionFactory() as session:
        matches = await retrieve_structured_property_matches(session, filters, dedupe=True)

    return {
        "tool": "search_properties",
        "status": "ok",
        "query_constructor": describe_query_constructor(filters),
        "result_count": len(matches),
        "results": [
            {
                "property_record": _serialize_property_record(match.property_record),
                "source_document": _serialize_source_document(match.source_document),
                "chunk": _serialize_chunk(match.chunk),
                "matched_fields": match.matched_fields,
                "relevance_score": _serialize_decimal(match.relevance_score),
                "selection_reason": match.selection_reason,
            }
            for match in matches
        ],
    }


async def aggregate_properties_tool(
    filters: dict[str, object],
    group_by: str | None = None,
    metrics: list[str] | None = None,
) -> dict[str, Any]:
    supported_metrics = {
        "count",
        "sum_sq_ft",
        "avg_sq_ft",
        "avg_price_per_sq_ft",
        "min_price_per_sq_ft",
        "max_price_per_sq_ft",
    }
    requested_metrics = metrics or ["count"]
    invalid_metrics = sorted(set(requested_metrics) - supported_metrics)
    if invalid_metrics:
        return {
            "tool": "aggregate_properties",
            "status": "invalid_metrics",
            "invalid_metrics": invalid_metrics,
            "supported_metrics": sorted(supported_metrics),
        }

    async with SessionFactory() as session:
        rows = list((await session.execute(build_property_query(filters))).all())

    deduped_rows = _dedupe_property_rows(rows)
    grouped: dict[str, dict[str, object]] = {}
    for property_record, source_document, chunk in deduped_rows:
        group_key, group_label = _group_key_for_row(property_record, source_document, group_by)
        group = grouped.setdefault(
            group_key,
            {
                "group_key": group_key,
                "group_label": group_label,
                "rows": [],
            },
        )
        group_rows = group["rows"]
        if isinstance(group_rows, list):
            group_rows.append((property_record, source_document, chunk))

    result_rows: list[dict[str, object]] = []
    for group in grouped.values():
        group_rows = list(group.pop("rows"))
        result_rows.append(
            {
                **group,
                "metrics": _metric_payload(group_rows, requested_metrics),
                "property_record_ids": [str(row[0].id) for row in group_rows],
                "source_document_ids": sorted({str(row[1].id) for row in group_rows}),
                "supporting_results": [_serialize_supporting_result(*row) for row in group_rows[:8]],
            }
        )

    result_rows.sort(key=lambda row: str(row["group_label"]))
    return {
        "tool": "aggregate_properties",
        "status": "ok",
        "query_constructor": describe_query_constructor(filters),
        "group_by": group_by,
        "metrics_requested": requested_metrics,
        "matched_record_count": len(deduped_rows),
        "result_count": len(result_rows),
        "evidence_ids": [],
        "evidence_note": "This read-only tool does not mint query evidence IDs; cite IDs from explain_evidence or backend-validated query evidence.",
        "rows": result_rows,
    }


async def search_source_chunks_tool(query: str, filters: dict[str, object] | None = None) -> dict[str, Any]:
    filters = filters or {}
    terms = _search_terms(query)
    if not terms:
        return {"tool": "search_source_chunks", "status": "invalid_query", "query": query}
    limit = int(filters.get("limit") or 10)

    ilike_filters = []
    for term in terms:
        ilike_filters.extend(
            [
                Chunk.chunk_text.ilike(f"%{term}%"),
                SourceDocument.raw_text.ilike(f"%{term}%"),
                SourceDocument.file_name.ilike(f"%{term}%"),
            ]
        )

    statement = (
        select(Chunk, SourceDocument, PropertyRecord)
        .join(SourceDocument, Chunk.document_id == SourceDocument.id)
        .outerjoin(PropertyRecord, PropertyRecord.chunk_id == Chunk.id)
        .where(or_(*ilike_filters))
    )

    property_types = [str(value) for value in filters.get("property_types") or []]
    if property_types:
        statement = statement.where(PropertyRecord.property_type.in_(property_types))

    uploader_names = [str(value).lower() for value in filters.get("uploader_names") or []]
    if uploader_names:
        statement = statement.where(func.lower(SourceDocument.slack_user_name).in_(uploader_names))

    source_types = [str(value) for value in filters.get("source_types") or []]
    if source_types:
        statement = statement.where(SourceDocument.source_type.in_(source_types))

    markets = [str(value) for value in filters.get("markets") or []]
    if markets:
        statement = statement.where(or_(*[PropertyRecord.market.ilike(f"%{market}%") for market in markets]))

    address_terms = [str(value) for value in filters.get("address_terms") or []]
    if address_terms:
        statement = statement.where(
            or_(
                *[
                    or_(
                        PropertyRecord.normalized_address.ilike(f"%{term}%"),
                        PropertyRecord.address.ilike(f"%{term}%"),
                    )
                    for term in address_terms
                ]
            )
        )

    file_name_contains = filters.get("file_name_contains")
    if file_name_contains:
        statement = statement.where(SourceDocument.file_name.ilike(f"%{file_name_contains}%"))

    vector_property_type = property_types[0] if len(property_types) == 1 else None
    vector_matches = await search_vector_chunks(
        query,
        property_type=vector_property_type,
        terms=terms,
        limit=limit,
        candidate_limit=max(20, limit * 3),
    )
    if vector_matches:
        vector_results: list[dict[str, object]] = []
        for match in vector_matches:
            if source_types and match.source_document.source_type not in source_types:
                continue
            if uploader_names and (match.source_document.slack_user_name or "").lower() not in uploader_names:
                continue
            if markets and (match.property_record is None or not any(market.lower() in (match.property_record.market or "").lower() for market in markets)):
                continue
            if address_terms and (
                match.property_record is None
                or not any(
                    term.lower() in (match.property_record.normalized_address or "").lower()
                    or term.lower() in (match.property_record.address or "").lower()
                    for term in address_terms
                )
            ):
                continue
            if file_name_contains and file_name_contains.lower() not in (match.source_document.file_name or "").lower():
                continue
            vector_results.append(
                {
                    "source_document": _serialize_source_document(match.source_document),
                    "chunk": _serialize_chunk(match.chunk),
                    "property_record": _serialize_property_record(match.property_record),
                    "matched_terms": match.matched_terms,
                    "relevance_score": _serialize_decimal(match.relevance_score),
                    "selection_reason": match.selection_reason,
                    "vector_score": f"{match.vector_score:.4f}",
                    "rerank_score": f"{match.rerank_score:.4f}" if match.rerank_score is not None else None,
                }
            )
        if vector_results:
            return {
                "tool": "search_source_chunks",
                "status": "ok",
                "query": query,
                "retrieval_mode": "qdrant_vector_rerank",
                "matched_terms": terms,
                "result_count": len(vector_results[:limit]),
                "results": vector_results[:limit],
            }

    async with SessionFactory() as session:
        rows = list((await session.execute(statement)).all())

    seen: set[tuple[str, str | None]] = set()
    results: list[dict[str, object]] = []
    for chunk, source_document, property_record in rows:
        dedupe_key = (str(chunk.id), str(property_record.id) if property_record is not None else None)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        haystack = " ".join(
            [
                chunk.chunk_text,
                source_document.raw_text or "",
                source_document.file_name or "",
                property_record.address if property_record is not None and property_record.address else "",
                property_record.market if property_record is not None and property_record.market else "",
            ]
        )
        matches = _matched_terms(haystack, terms)
        if not matches:
            continue
        authority = float(property_record.source_authority_score or Decimal("0")) if property_record is not None else 0.0
        freshness = float(property_record.freshness_score or Decimal("0")) if property_record is not None else 0.0
        results.append(
            {
                "source_document": _serialize_source_document(source_document),
                "chunk": _serialize_chunk(chunk),
                "property_record": _serialize_property_record(property_record),
                "matched_terms": matches,
                "relevance_score": _bounded_score(0.45 + (0.12 * len(matches)) + (0.15 * authority) + (0.08 * freshness)),
                "selection_reason": f"keyword chunk search matched: {', '.join(matches)}",
            }
        )

    results.sort(key=lambda item: str(item["relevance_score"]), reverse=True)
    return {
        "tool": "search_source_chunks",
        "status": "ok",
        "query": query,
        "retrieval_mode": "keyword_chunk_search",
        "matched_terms": terms,
        "result_count": len(results[:limit]),
        "results": results[:limit],
    }


async def _resolve_origin(origin: object) -> dict[str, object] | None:
    if isinstance(origin, dict):
        lat_value = origin.get("lat") or origin.get("geo_lat")
        lng_value = origin.get("lng") or origin.get("lon") or origin.get("geo_lng")
        if lat_value is not None and lng_value is not None:
            return {
                "label": origin.get("label") or origin.get("address") or "provided coordinates",
                "lat": float(lat_value),
                "lng": float(lng_value),
                "property_record_id": None,
                "duplicate_group_key": None,
            }
        if origin.get("address"):
            origin = str(origin["address"])

    if not isinstance(origin, str) or not origin.strip():
        return None

    normalized_origin = _normalize_text(origin)
    async with SessionFactory() as session:
        statement = (
            select(PropertyRecord, SourceDocument)
            .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
            .where(PropertyRecord.geo_lat.is_not(None), PropertyRecord.geo_lng.is_not(None))
            .where(
                or_(
                    PropertyRecord.normalized_address == normalized_origin,
                    PropertyRecord.normalized_address.ilike(f"%{normalized_origin}%"),
                    PropertyRecord.address.ilike(f"%{origin}%"),
                )
            )
        )
        rows = list((await session.execute(statement)).all())

    if not rows:
        return None
    property_record, source_document = max(rows, key=lambda row: _property_priority(row[0], row[1]))
    return {
        "label": property_record.address or origin,
        "lat": float(property_record.geo_lat),
        "lng": float(property_record.geo_lng),
        "property_record_id": str(property_record.id),
        "duplicate_group_key": property_record.duplicate_group_key,
        "source_document": _serialize_source_document(source_document),
    }


async def nearby_properties_tool(origin: object, radius_miles: float, filters: dict[str, object] | None = None) -> dict[str, Any]:
    filters = filters or {}
    if radius_miles <= 0:
        return {"tool": "nearby_properties", "status": "invalid_radius", "radius_miles": radius_miles}

    resolved_origin = await _resolve_origin(origin)
    if resolved_origin is None:
        return {"tool": "nearby_properties", "status": "origin_not_found", "origin": origin}

    async with SessionFactory() as session:
        statement = build_property_query(filters).where(PropertyRecord.geo_lat.is_not(None), PropertyRecord.geo_lng.is_not(None))
        rows = _dedupe_property_rows(list((await session.execute(statement)).all()))

    results: list[dict[str, object]] = []
    origin_duplicate_key = resolved_origin.get("duplicate_group_key")
    for property_record, source_document, chunk in rows:
        if str(property_record.id) == resolved_origin.get("property_record_id"):
            continue
        if origin_duplicate_key and property_record.duplicate_group_key == origin_duplicate_key:
            continue
        if property_record.geo_lat is None or property_record.geo_lng is None:
            continue
        distance = _distance_miles(
            float(resolved_origin["lat"]),
            float(resolved_origin["lng"]),
            float(property_record.geo_lat),
            float(property_record.geo_lng),
        )
        if distance > radius_miles:
            continue
        results.append(
            {
                "distance_miles": round(distance, 3),
                "property_record": _serialize_property_record(property_record),
                "source_document": _serialize_source_document(source_document),
                "chunk": _serialize_chunk(chunk),
                "matched_fields": ["geo_lat", "geo_lng"],
                "relevance_score": _bounded_score(1 / (1 + distance)),
                "selection_reason": "distance-ranked from backend geospatial calculation",
            }
        )

    results.sort(key=lambda item: (float(item["distance_miles"]), str(item["property_record"])))
    limit = int(filters.get("limit") or 5)
    return {
        "tool": "nearby_properties",
        "status": "ok",
        "origin": resolved_origin,
        "radius_miles": radius_miles,
        "query_constructor": describe_query_constructor(filters),
        "result_count": len(results[:limit]),
        "results": results[:limit],
    }


async def audit_data_tool() -> dict[str, Any]:
    async with SessionFactory() as session:
        report = await collect_data_quality_report(session)
    return {"tool": "audit_data", "status": "ok", **report}


async def get_source_detail_tool(source_id: str) -> dict[str, Any]:
    try:
        parsed_source_id = UUID(source_id)
    except ValueError:
        return {"tool": "get_source_detail", "status": "invalid_source_id", "source_id": source_id}

    async with SessionFactory() as session:
        source_document = await session.get(SourceDocument, parsed_source_id)
        if source_document is None:
            return {"tool": "get_source_detail", "status": "not_found", "source_id": source_id}

        chunks = list((await session.execute(select(Chunk).where(Chunk.document_id == parsed_source_id).order_by(Chunk.chunk_index))).scalars())
        properties = list((await session.execute(select(PropertyRecord).where(PropertyRecord.document_id == parsed_source_id).order_by(PropertyRecord.address))).scalars())

    return {
        "tool": "get_source_detail",
        "status": "ok",
        "source_document": _serialize_source_document(source_document),
        "chunks": [_serialize_chunk(chunk) for chunk in chunks],
        "property_records": [_serialize_property_record(property_record) for property_record in properties],
    }


async def local_deeper_review_tool(query_id: str) -> dict[str, Any]:
    return {
        "tool": "local_deeper_review",
        "status": "ok",
        "payload": await run_local_deeper_review(query_id),
    }


async def explain_query_tool(query_id: str) -> dict[str, Any]:
    return {
        "tool": "explain_query",
        "status": "ok",
        "payload": await explain_query(query_id),
    }


__all__ = [
    "aggregate_properties_tool",
    "audit_data_tool",
    "explain_evidence_tool",
    "explain_query_tool",
    "get_source_detail_tool",
    "local_deeper_review_tool",
    "nearby_properties_tool",
    "search_source_chunks_tool",
    "search_properties_tool",
]
