from __future__ import annotations

import math
import re
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import String, func, or_, select

from app.answering.query_service import explain_query
from app.db.session import SessionFactory
from app.indexing import search_vector_chunks
from app.models import AnswerSnapshot, Chunk, EvidenceItem, PropertyRecord, Query, SourceDocument
from app.retrieval import build_property_query, collect_data_quality_report, describe_query_constructor, retrieve_structured_property_matches
from app.toolhouse.evidence_context import build_backend_schema_context
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


def _source_label(source_document: SourceDocument) -> str:
    if source_document.file_name:
        return source_document.file_name
    if source_document.source_type == "slack_message":
        return "Slack message"
    return source_document.source_type


def _source_summary(
    property_record: PropertyRecord,
    source_document: SourceDocument,
    chunk: Chunk | None,
) -> str:
    details: list[str] = []
    if property_record.source_page is not None:
        details.append(f"p. {property_record.source_page}")
    elif chunk is not None and chunk.page_number is not None:
        details.append(f"p. {chunk.page_number}")
    if property_record.source_row is not None:
        details.append(f"row {property_record.source_row}")
    elif chunk is not None and chunk.row_number is not None:
        details.append(f"row {chunk.row_number}")
    if source_document.slack_user_name:
        details.append(source_document.slack_user_name)
    if source_document.slack_channel_name:
        details.append(f"#{source_document.slack_channel_name}")
    if source_document.posted_at is not None:
        details.append(source_document.posted_at.date().isoformat())
    return _source_label(source_document) if not details else f"{_source_label(source_document)} ({'; '.join(details)})"


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


async def describe_backend_schema_tool() -> dict[str, Any]:
    return {"tool": "describe_backend_schema", "status": "ok", **build_backend_schema_context()}


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


def _evidence_key(
    document_id: object,
    chunk_id: object,
    property_record_id: object,
) -> tuple[str | None, str | None, str | None]:
    return (
        str(document_id) if document_id is not None else None,
        str(chunk_id) if chunk_id is not None else None,
        str(property_record_id) if property_record_id is not None else None,
    )


async def expand_query_evidence_tool(
    query_id: str,
    filters: dict[str, object],
    reason: str | None = None,
) -> dict[str, Any]:
    try:
        parsed_query_id = UUID(query_id)
    except ValueError:
        return {"tool": "expand_query_evidence", "status": "invalid_query_id", "query_id": query_id}

    bounded_filters = dict(filters or {})
    requested_limit = int(bounded_filters.get("limit") or 10)
    bounded_filters["limit"] = max(1, min(50, requested_limit))

    async with SessionFactory() as session:
        async with session.begin():
            query_record = await session.get(Query, parsed_query_id)
            if query_record is None:
                return {"tool": "expand_query_evidence", "status": "query_not_found", "query_id": query_id}

            snapshot = await session.scalar(select(AnswerSnapshot).where(AnswerSnapshot.query_id == parsed_query_id))
            if snapshot is None:
                return {"tool": "expand_query_evidence", "status": "snapshot_not_found", "query_id": query_id}

            matches = await retrieve_structured_property_matches(session, bounded_filters, dedupe=True)
            existing_rows = list((await session.execute(select(EvidenceItem).where(EvidenceItem.query_id == parsed_query_id))).scalars())
            existing_by_key = {
                _evidence_key(row.document_id, row.chunk_id, row.property_record_id): row
                for row in existing_rows
            }

            result_records: list[tuple[EvidenceItem, object, object, object, bool]] = []
            for match in matches:
                key = _evidence_key(
                    match.source_document.id,
                    match.chunk.id if match.chunk is not None else None,
                    match.property_record.id,
                )
                existing = existing_by_key.get(key)
                if existing is not None:
                    result_records.append((existing, match.property_record, match.source_document, match.chunk, False))
                    continue

                evidence_record = EvidenceItem(
                    query_id=parsed_query_id,
                    document_id=match.source_document.id,
                    chunk_id=match.chunk.id if match.chunk is not None else None,
                    property_record_id=match.property_record.id,
                    relevance_score=match.relevance_score,
                    matched_fields=match.matched_fields,
                    source_summary=_source_summary(match.property_record, match.source_document, match.chunk),
                )
                session.add(evidence_record)
                result_records.append((evidence_record, match.property_record, match.source_document, match.chunk, True))

            await session.flush()

            ordered_ids = list(snapshot.evidence_ids or [])
            existing_order = {str(value) for value in ordered_ids}
            for evidence_record, _, _, _, _ in result_records:
                evidence_id = str(evidence_record.id)
                if evidence_id not in existing_order:
                    ordered_ids.append(evidence_record.id)
                    existing_order.add(evidence_id)
            snapshot.evidence_ids = ordered_ids

            filters_json = dict(snapshot.filters_json or {})
            expansions = list(filters_json.get("evidence_expansions") or [])
            expansions.append(
                {
                    "tool": "expand_query_evidence",
                    "reason": reason or "Toolhouse requested additional backend evidence for this query.",
                    "filters": bounded_filters,
                    "query_constructor": describe_query_constructor(bounded_filters),
                    "matched_count": len(result_records),
                    "added_count": sum(1 for _, _, _, _, added in result_records if added),
                }
            )
            filters_json["evidence_expansions"] = expansions[-10:]
            snapshot.filters_json = filters_json

            results = [
                {
                    "evidence_id": str(evidence_record.id),
                    "was_added": was_added,
                    "property_record": _serialize_property_record(property_record),
                    "source_document": _serialize_source_document(source_document),
                    "chunk": _serialize_chunk(chunk),
                    "matched_fields": list(evidence_record.matched_fields or []),
                    "relevance_score": _serialize_decimal(evidence_record.relevance_score),
                    "selection_reason": evidence_record.source_summary,
                }
                for evidence_record, property_record, source_document, chunk, was_added in result_records
            ]

            return {
                "tool": "expand_query_evidence",
                "status": "ok" if results else "no_results",
                "query_id": query_id,
                "query_constructor": describe_query_constructor(bounded_filters),
                "reason": reason,
                "result_count": len(results),
                "added_count": sum(1 for item in results if item["was_added"]),
                "allowed_evidence_ids_added": [item["evidence_id"] for item in results if item["was_added"]],
                "allowed_evidence_ids_reused": [item["evidence_id"] for item in results if not item["was_added"]],
                "allowed_evidence_ids_total": [str(value) for value in ordered_ids],
                "evidence_note": "These IDs are now backend-minted evidence for the original query and may be cited after validation refresh.",
                "results": results,
            }


def _evidence_ids_by_property(expansion_payload: dict[str, Any]) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for item in list(expansion_payload.get("results") or []):
        property_record = dict(item.get("property_record") or {})
        property_id = property_record.get("id")
        evidence_id = item.get("evidence_id")
        if property_id and evidence_id:
            mapping[str(property_id)] = str(evidence_id)
    return mapping


def _objective_terms(objective: str | None, keywords: list[str] | None) -> set[str]:
    raw_terms = [objective or "balanced", *(keywords or [])]
    terms: set[str] = set()
    for value in raw_terms:
        normalized = _normalize_text(str(value))
        terms.update(term for term in re.findall(r"[a-z0-9][a-z0-9-]{2,}", normalized) if term)
    return terms


def _rank_property(
    property_record: PropertyRecord,
    source_document: SourceDocument,
    chunk: Chunk | None,
    *,
    objective: str | None,
    keywords: list[str] | None,
) -> tuple[float, list[str]]:
    terms = _objective_terms(objective, keywords)
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    confidence = float(property_record.confidence or Decimal("0"))
    price = float(property_record.price_per_sq_ft or Decimal("999"))
    sq_ft = float(property_record.sq_ft or 0)
    chunk_text = chunk.chunk_text.lower() if chunk is not None else ""
    haystack = " ".join(
        [
            property_record.address or "",
            property_record.property_type or "",
            property_record.market or "",
            property_record.availability or "",
            chunk_text,
        ]
    ).lower()

    reasons: list[str] = []
    score = 0.20 + (0.20 * authority) + (0.16 * freshness) + (0.08 * confidence)

    if any(term in terms for term in {"cheap", "cheapest", "price", "rent", "budget", "low"}):
        price_score = max(0.0, min(0.30, (60.0 - min(price, 60.0)) / 200.0))
        score += price_score
        if property_record.price_per_sq_ft is not None:
            reasons.append(f"lower rent at ${property_record.price_per_sq_ft}/SF")

    if any(term in terms for term in {"large", "largest", "scale", "sf", "space", "square"}):
        size_score = max(0.0, min(0.24, sq_ft / 500000.0))
        score += size_score
        if property_record.sq_ft is not None:
            reasons.append(f"larger block at {property_record.sq_ft:,} SF")

    if any(term in terms for term in {"soon", "immediate", "available", "availability", "urgent"}):
        if property_record.availability_date is not None and property_record.availability_date <= date(2026, 8, 31):
            score += 0.18
            reasons.append("near-term availability")
        elif property_record.availability and any(marker in property_record.availability.lower() for marker in ("immediate", "now")):
            score += 0.18
            reasons.append("available now wording")

    if any(term in terms for term in {"tenant", "fit", "logistics", "warehouse", "truck", "yard", "dock", "loading"}):
        if property_record.property_type == "industrial":
            score += 0.10
            reasons.append("industrial fit")
        if property_record.price_per_sq_ft is not None and property_record.price_per_sq_ft <= Decimal("35"):
            score += 0.10
            reasons.append("under $35/SF")
        if property_record.sq_ft is not None and property_record.sq_ft >= 15000:
            score += 0.08
            reasons.append("usable logistics scale")

    matched_terms = sorted(term for term in terms if term in haystack)
    if matched_terms:
        score += min(0.18, 0.04 * len(matched_terms))
        reasons.append(f"matched language: {', '.join(matched_terms[:5])}")

    if not reasons:
        reasons.append("best blend of source authority, freshness, and structured completeness")
    return max(0.0500, min(0.9999, score)), reasons


async def rank_properties_tool(
    filters: dict[str, object],
    objective: str = "balanced",
    keywords: list[str] | None = None,
    query_id: str | None = None,
) -> dict[str, Any]:
    bounded_filters = dict(filters or {})
    bounded_filters["limit"] = max(1, min(50, int(bounded_filters.get("limit") or 10)))
    async with SessionFactory() as session:
        matches = await retrieve_structured_property_matches(session, bounded_filters, dedupe=True)

    evidence_by_property: dict[str, str] = {}
    expansion_payload: dict[str, Any] | None = None
    if query_id:
        expansion_payload = await expand_query_evidence_tool(
            query_id,
            bounded_filters,
            reason=f"rank_properties objective={objective}",
        )
        evidence_by_property = _evidence_ids_by_property(expansion_payload)

    ranked: list[dict[str, object]] = []
    for match in matches:
        score, reasons = _rank_property(
            match.property_record,
            match.source_document,
            match.chunk,
            objective=objective,
            keywords=keywords,
        )
        property_id = str(match.property_record.id)
        ranked.append(
            {
                "rank_score": f"{score:.4f}",
                "rank_reasons": reasons,
                "evidence_id": evidence_by_property.get(property_id),
                "property_record": _serialize_property_record(match.property_record),
                "source_document": _serialize_source_document(match.source_document),
                "chunk": _serialize_chunk(match.chunk),
                "matched_fields": match.matched_fields,
                "selection_reason": match.selection_reason,
            }
        )

    ranked.sort(key=lambda item: (str(item["rank_score"]), str((item["property_record"] or {}).get("address") if isinstance(item["property_record"], dict) else "")), reverse=True)
    return {
        "tool": "rank_properties",
        "status": "ok" if ranked else "no_results",
        "objective": objective,
        "keywords": keywords or [],
        "query_id": query_id,
        "query_constructor": describe_query_constructor(bounded_filters),
        "result_count": len(ranked),
        "evidence_expansion": expansion_payload,
        "evidence_note": "When query_id is provided, returned evidence_id values are backend-minted and may be cited after validation refresh.",
        "results": ranked,
    }


async def summarize_inventory_tool(
    filters: dict[str, object] | None = None,
    query_id: str | None = None,
) -> dict[str, Any]:
    base_filters = dict(filters or {})
    base_filters["limit"] = max(1, min(50, int(base_filters.get("limit") or 25)))
    by_type = await aggregate_properties_tool(base_filters, group_by="property_type", metrics=["count", "sum_sq_ft", "avg_price_per_sq_ft", "min_price_per_sq_ft", "max_price_per_sq_ft"])
    by_market = await aggregate_properties_tool(base_filters, group_by="market", metrics=["count", "avg_price_per_sq_ft", "min_price_per_sq_ft", "max_price_per_sq_ft"])
    cheapest = await rank_properties_tool({**base_filters, "sort": "price_asc", "limit": min(8, int(base_filters["limit"]))}, objective="cheapest", query_id=query_id)
    largest = await rank_properties_tool({**base_filters, "sort": "size_desc", "limit": min(8, int(base_filters["limit"]))}, objective="largest", query_id=query_id)
    soonest = await rank_properties_tool({**base_filters, "sort": "availability_asc", "limit": min(8, int(base_filters["limit"]))}, objective="available soon", query_id=query_id)
    return {
        "tool": "summarize_inventory",
        "status": "ok",
        "query_id": query_id,
        "query_constructor": describe_query_constructor(base_filters),
        "by_property_type": by_type,
        "by_market": by_market,
        "ranked_slices": {
            "cheapest": cheapest,
            "largest": largest,
            "soonest_available": soonest,
        },
        "evidence_note": "Ranked slices mint query-scoped evidence IDs when query_id is provided.",
    }


async def get_property_timeline_tool(property_ref: str, query_id: str | None = None) -> dict[str, Any]:
    if not property_ref.strip():
        return {"tool": "get_property_timeline", "status": "invalid_property_ref", "property_ref": property_ref}

    normalized_ref = _normalize_text(property_ref)
    async with SessionFactory() as session:
        initial_rows = list(
            (
                await session.execute(
                    select(PropertyRecord, SourceDocument, Chunk)
                    .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
                    .outerjoin(Chunk, PropertyRecord.chunk_id == Chunk.id)
                    .where(
                        or_(
                            PropertyRecord.id.cast(String) == property_ref,
                            PropertyRecord.duplicate_group_key == property_ref,
                            PropertyRecord.normalized_address.ilike(f"%{normalized_ref}%"),
                            PropertyRecord.address.ilike(f"%{property_ref}%"),
                        )
                    )
                )
            ).all()
        )

    if not initial_rows:
        return {"tool": "get_property_timeline", "status": "not_found", "property_ref": property_ref}

    duplicate_keys = {row[0].duplicate_group_key for row in initial_rows if row[0].duplicate_group_key}
    if duplicate_keys:
        async with SessionFactory() as session:
            rows = list(
                (
                    await session.execute(
                        select(PropertyRecord, SourceDocument, Chunk)
                        .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
                        .outerjoin(Chunk, PropertyRecord.chunk_id == Chunk.id)
                        .where(PropertyRecord.duplicate_group_key.in_(duplicate_keys))
                    )
                ).all()
            )
    else:
        rows = initial_rows

    rows.sort(key=lambda row: (row[1].posted_at or row[0].created_at, row[0].address or ""))
    expansion_payload = None
    evidence_by_property: dict[str, str] = {}
    if query_id:
        expansion_payload = await expand_query_evidence_tool(
            query_id,
            {"address_terms": [normalized_ref], "limit": min(50, max(10, len(rows)))},
            reason=f"get_property_timeline property_ref={property_ref}",
        )
        evidence_by_property = _evidence_ids_by_property(expansion_payload)

    timeline = []
    for property_record, source_document, chunk in rows:
        timeline.append(
            {
                "posted_at": source_document.posted_at.isoformat() if source_document.posted_at else None,
                "evidence_id": evidence_by_property.get(str(property_record.id)),
                "property_record": _serialize_property_record(property_record),
                "source_document": _serialize_source_document(source_document),
                "chunk": _serialize_chunk(chunk),
                "source_summary": _source_summary(property_record, source_document, chunk),
            }
        )

    return {
        "tool": "get_property_timeline",
        "status": "ok",
        "property_ref": property_ref,
        "duplicate_group_keys": sorted(duplicate_keys),
        "event_count": len(timeline),
        "evidence_expansion": expansion_payload,
        "timeline": timeline,
    }


def _conflict_payload(rows: list[tuple[PropertyRecord, SourceDocument, Chunk | None]]) -> dict[str, object] | None:
    sq_ft_values = sorted({row[0].sq_ft for row in rows if row[0].sq_ft is not None})
    price_values = sorted({str(row[0].price_per_sq_ft) for row in rows if row[0].price_per_sq_ft is not None})
    availability_values = sorted({row[0].availability for row in rows if row[0].availability})
    conflict_fields = []
    if len(sq_ft_values) > 1:
        conflict_fields.append("sq_ft")
    if len(price_values) > 1:
        conflict_fields.append("price_per_sq_ft")
    if len(availability_values) > 1:
        conflict_fields.append("availability")
    if not conflict_fields:
        return None
    selected = max(rows, key=lambda row: _property_priority(row[0], row[1]))
    return {
        "duplicate_group_key": rows[0][0].duplicate_group_key,
        "address": selected[0].address,
        "conflict_fields": conflict_fields,
        "sq_ft_values": sq_ft_values,
        "price_per_sq_ft_values": price_values,
        "availability_values": availability_values,
        "selected_record_id": str(selected[0].id),
        "selected_reason": "highest source authority, freshness, and posting-time priority",
        "records": [_serialize_supporting_result(*row) for row in sorted(rows, key=lambda row: _property_priority(row[0], row[1]), reverse=True)],
    }


async def find_property_conflicts_tool(
    filters: dict[str, object] | None = None,
    query_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    bounded_filters = dict(filters or {})
    bounded_filters["limit"] = max(1, min(100, int(bounded_filters.get("limit") or 100)))
    async with SessionFactory() as session:
        rows = list((await session.execute(build_property_query(bounded_filters))).all())

    groups: dict[str, list[tuple[PropertyRecord, SourceDocument, Chunk | None]]] = {}
    for row in rows:
        property_record = row[0]
        if not property_record.duplicate_group_key:
            continue
        groups.setdefault(property_record.duplicate_group_key, []).append(row)

    conflicts = []
    for group_rows in groups.values():
        payload = _conflict_payload(group_rows)
        if payload is not None:
            conflicts.append(payload)
    conflicts.sort(key=lambda item: str(item.get("address") or item.get("duplicate_group_key") or ""))
    conflicts = conflicts[: max(1, min(25, int(limit)))]

    expansion_payloads = []
    if query_id:
        for conflict in conflicts:
            address = str(conflict.get("address") or "")
            if not address:
                continue
            expansion_payloads.append(
                await expand_query_evidence_tool(
                    query_id,
                    {"address_terms": [_normalize_text(address)], "limit": 10},
                    reason=f"find_property_conflicts address={address}",
                )
            )

    return {
        "tool": "find_property_conflicts",
        "status": "ok" if conflicts else "no_conflicts",
        "query_id": query_id,
        "query_constructor": describe_query_constructor(bounded_filters),
        "conflict_count": len(conflicts),
        "evidence_expansions": expansion_payloads,
        "conflicts": conflicts,
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


async def expand_query_context_tool(
    query_id: str,
    *,
    include_source_details: bool = True,
    max_sources: int = 8,
) -> dict[str, Any]:
    escalation_payload = await build_escalation_payload(query_id)
    if escalation_payload.get("status") != "ready":
        return {
            "tool": "expand_query_context",
            "status": escalation_payload.get("status") or "not_ready",
            "query_id": query_id,
            "payload": escalation_payload,
        }

    evidence = list(escalation_payload.get("evidence") or [])
    source_ids: list[str] = []
    for item in evidence:
        source_document = dict(item.get("source_document") or {})
        source_id = source_document.get("id")
        if source_id and str(source_id) not in source_ids:
            source_ids.append(str(source_id))

    bounded_max_sources = max(0, min(15, int(max_sources)))
    source_details = []
    if include_source_details:
        for source_id in source_ids[:bounded_max_sources]:
            source_details.append(await get_source_detail_tool(source_id))

    filters = dict(escalation_payload.get("filters") or {})
    aggregate_metrics = ["count", "sum_sq_ft", "avg_price_per_sq_ft", "min_price_per_sq_ft", "max_price_per_sq_ft"]
    aggregate_summaries = [
        await aggregate_properties_tool(filters, group_by="property_type", metrics=aggregate_metrics),
        await aggregate_properties_tool(filters, group_by="market", metrics=["count", "avg_price_per_sq_ft"]),
    ]

    return {
        "tool": "expand_query_context",
        "status": "ok",
        "query_id": query_id,
        "evidence_context": escalation_payload.get("evidence_context"),
        "source_details_included": include_source_details,
        "source_detail_count": len(source_details),
        "source_details": source_details,
        "aggregate_summaries": aggregate_summaries,
        "allowed_evidence_ids": escalation_payload.get("allowed_evidence_ids", []),
        "evidence_note": "Use expand_query_evidence if a newly discovered structured result needs a citable evidence ID.",
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
    "describe_backend_schema_tool",
    "explain_evidence_tool",
    "explain_query_tool",
    "expand_query_context_tool",
    "expand_query_evidence_tool",
    "find_property_conflicts_tool",
    "get_source_detail_tool",
    "get_property_timeline_tool",
    "local_deeper_review_tool",
    "nearby_properties_tool",
    "rank_properties_tool",
    "search_source_chunks_tool",
    "search_properties_tool",
    "summarize_inventory_tool",
]
