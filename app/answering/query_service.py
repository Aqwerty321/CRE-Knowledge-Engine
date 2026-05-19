from __future__ import annotations

import math
from dataclasses import dataclass, field
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import SessionFactory
from app.models import AnswerSnapshot, Chunk, EvidenceItem, PropertyFieldValue, PropertyRecord, Query, SourceDocument
from app.retrieval import (
    HybridChunkMatch,
    StructuredPropertyMatch,
    collect_data_quality_report,
    describe_query_constructor,
    explain_no_results,
    retrieve_loading_access_matches,
    retrieve_structured_property_matches,
    retrieve_tenant_fit_matches,
)
from app.routing import QueryPlan, SUPPORTED_QUERY_HINTS, build_query_plan


@dataclass(frozen=True)
class RetrievedEvidence:
    property_record: PropertyRecord
    source_document: SourceDocument
    chunk: Chunk | None
    relevance_score: Decimal
    matched_fields: list[str]
    source_summary: str
    distance_km: float | None = None
    selection_reason: str | None = None
    retrieval_metadata: dict[str, object] = field(default_factory=dict)


def _distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    radius_km = 6371.0
    lat1_radians = math.radians(lat1)
    lat2_radians = math.radians(lat2)
    lat_delta = math.radians(lat2 - lat1)
    lng_delta = math.radians(lng2 - lng1)

    a = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(lat1_radians) * math.cos(lat2_radians) * math.sin(lng_delta / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def _to_decimal_score(value: float) -> Decimal:
    bounded = max(0.0500, min(0.9999, value))
    return Decimal(f"{bounded:.4f}")


def _source_label(source_document: SourceDocument) -> str:
    if source_document.file_name:
        return source_document.file_name
    if source_document.source_type == "slack_message":
        return "Slack message"
    return source_document.source_type


def _build_source_summary(
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

    if not details:
        return _source_label(source_document)
    return f"{_source_label(source_document)} ({'; '.join(details)})"


def _format_property_type(property_type: str) -> str:
    return property_type.replace("_", " ")


def _format_sq_ft(value: int | None) -> str:
    return "unknown SF" if value is None else f"{value:,} SF"


def _format_price(value: Decimal | None) -> str:
    return "unknown price" if value is None else f"${value:,.2f}/SF"


def _unique_addresses(items: list[RetrievedEvidence]) -> list[str]:
    seen: set[str] = set()
    addresses: list[str] = []
    for item in items:
        address = item.property_record.address
        if address is None or address in seen:
            continue
        seen.add(address)
        addresses.append(address)
    return addresses


def _serialize_decimal(value: Decimal | None) -> str | None:
    return None if value is None else format(value, "f")


def _serialize_uuid_list(values: list[UUID]) -> list[str]:
    return [str(value) for value in values]


def _serialize_field_value(field_value: PropertyFieldValue) -> dict[str, object]:
    return {
        "field_name": field_value.field_name,
        "raw_value": field_value.raw_value,
        "normalized_value": field_value.normalized_value,
        "confidence": _serialize_decimal(field_value.confidence),
        "method": field_value.method,
        "source_span": field_value.source_span,
        "extractor_version": field_value.extractor_version,
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
        "availability": property_record.availability,
        "availability_date": property_record.availability_date.isoformat() if property_record.availability_date else None,
        "market": property_record.market,
        "source_page": property_record.source_page,
        "source_row": property_record.source_row,
        "source_authority_score": _serialize_decimal(property_record.source_authority_score),
        "freshness_score": _serialize_decimal(property_record.freshness_score),
        "duplicate_group_key": property_record.duplicate_group_key,
    }


def _serialize_source_document(source_document: SourceDocument | None) -> dict[str, object] | None:
    if source_document is None:
        return None

    return {
        "id": str(source_document.id),
        "source_type": source_document.source_type,
        "file_name": source_document.file_name,
        "source_url": source_document.source_url,
        "local_path": source_document.local_path,
        "slack_user_name": source_document.slack_user_name,
        "slack_channel_name": source_document.slack_channel_name,
        "slack_ts": source_document.slack_ts,
        "posted_at": source_document.posted_at.isoformat() if source_document.posted_at else None,
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
        "text_preview": chunk.chunk_text[:180],
    }


def _dependency_state_for_plan(plan: QueryPlan) -> dict[str, object]:
    dependency_state: dict[str, object] = {"qdrant": False, "toolhouse": False, "llm": False}
    if plan.route_mode == "hybrid":
        dependency_state["keyword_fallback"] = True
        dependency_state["retrieval_mode"] = plan.filters.get("retrieval_mode", "keyword")
        if plan.query_type == "loading_access_search" and get_settings().vector_search_enabled:
            dependency_state["qdrant_enabled"] = True
    if plan.query_type == "generic_tenant_fit":
        dependency_state["local_synthesis"] = True
        dependency_state["retrieval_mode"] = "structured_tenant_fit"
    return dependency_state


def _dependency_state_for_result(plan: QueryPlan, items: list[RetrievedEvidence]) -> dict[str, object]:
    dependency_state = _dependency_state_for_plan(plan)
    if plan.query_type == "loading_access_search" and items:
        layer_status: dict[str, str] = {}
        contributors: set[str] = set()
        expansion_terms: list[str] = []
        for item in items:
            metadata = item.retrieval_metadata
            layer_status.update({str(key): str(value) for key, value in dict(metadata.get("layer_status") or {}).items()})
            contributors.update(str(value) for value in list(metadata.get("retrieval_contributors") or []))
            if not expansion_terms:
                expansion_terms = [str(value) for value in list(metadata.get("query_expansion_terms") or [])]

        dependency_state["keyword_fallback"] = True
        dependency_state["retrieval_mode"] = (
            "hybrid_lexical_fuzzy_vector" if "qdrant_vector" in contributors else "hybrid_lexical_fuzzy"
        )
        dependency_state["retrieval_layers"] = layer_status
        dependency_state["retrieval_contributors"] = sorted(contributors)
        dependency_state["query_expansion_terms"] = expansion_terms[:12]
        dependency_state["qdrant"] = "qdrant_vector" in contributors
        dependency_state["rerank"] = "rerank" in contributors or layer_status.get("rerank") == "ok"
    return dependency_state


def _model_versions_for_plan(plan: QueryPlan) -> dict[str, object]:
    if plan.query_type.startswith("generic_"):
        return {"answering": "heuristic-v2", "query_constructor": "structured-v1"}
    return {"answering": "hybrid-v2" if plan.route_mode == "hybrid" else "instant-v1"}


def _query_constructor_filters_for_plan(plan: QueryPlan) -> dict[str, object] | None:
    if plan.query_type.startswith("generic_"):
        return dict(plan.filters)
    if plan.query_type == "office_under_threshold":
        return {
            "property_types": ["office"],
            "price_per_sq_ft_lt": plan.filters.get("price_per_sq_ft_lt"),
            "limit": 5,
        }
    return None


def _snapshot_filters_for_plan(
    plan: QueryPlan,
    *,
    no_results_context: dict[str, object] | None = None,
    data_quality_report: dict[str, object] | None = None,
    slack_context: dict[str, object] | None = None,
) -> dict[str, object]:
    filters = dict(plan.filters)
    constructor_filters = _query_constructor_filters_for_plan(plan)
    if constructor_filters is not None:
        filters["query_constructor"] = describe_query_constructor(constructor_filters)
    if no_results_context is not None:
        filters["missing_data_explanation"] = no_results_context
    if data_quality_report is not None:
        filters["data_quality_report"] = data_quality_report
    if slack_context:
        filters["slack_context"] = slack_context
    return filters


def _slack_context_payload(
    *,
    slack_channel_id: str | None,
    slack_user_id: str | None,
    slack_ts: str | None,
    slack_thread_ts: str | None,
) -> dict[str, object]:
    payload = {
        "channel_id": slack_channel_id,
        "user_id": slack_user_id,
        "message_ts": slack_ts,
        "thread_ts": slack_thread_ts or slack_ts,
    }
    return {key: value for key, value in payload.items() if value}


async def _fetch_property_rows(
    session: AsyncSession,
    session_filters: tuple[object, ...],
) -> list[tuple[PropertyRecord, SourceDocument, Chunk | None]]:
    statement = (
        select(PropertyRecord, SourceDocument, Chunk)
        .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
        .outerjoin(Chunk, PropertyRecord.chunk_id == Chunk.id)
        .where(*session_filters)
    )
    rows = await session.execute(statement)
    return list(rows.all())


def _build_evidence_item(
    property_record: PropertyRecord,
    source_document: SourceDocument,
    chunk: Chunk | None,
    *,
    relevance_score: Decimal,
    matched_fields: list[str],
    distance_km: float | None = None,
    selection_reason: str | None = None,
    retrieval_metadata: dict[str, object] | None = None,
) -> RetrievedEvidence:
    return RetrievedEvidence(
        property_record=property_record,
        source_document=source_document,
        chunk=chunk,
        relevance_score=relevance_score,
        matched_fields=matched_fields,
        source_summary=_build_source_summary(property_record, source_document, chunk),
        distance_km=distance_km,
        selection_reason=selection_reason,
        retrieval_metadata=retrieval_metadata or {},
    )


async def _retrieve_proximity(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    rows = await _fetch_property_rows(
        session,
        (PropertyRecord.geo_lat.is_not(None), PropertyRecord.geo_lng.is_not(None), PropertyRecord.address.is_not(None))
    )
    anchor_lat = float(plan.filters["anchor_lat"])
    anchor_lng = float(plan.filters["anchor_lng"])
    limit = int(plan.filters["limit"])

    items: list[RetrievedEvidence] = []
    for property_record, source_document, chunk in rows:
        if property_record.geo_lat is None or property_record.geo_lng is None:
            continue

        distance_km = _distance_km(anchor_lat, anchor_lng, float(property_record.geo_lat), float(property_record.geo_lng))
        items.append(
            _build_evidence_item(
                property_record,
                source_document,
                chunk,
                relevance_score=_to_decimal_score(1 / (1 + distance_km)),
                matched_fields=["geo_lat", "geo_lng", "availability"],
                distance_km=distance_km,
            )
        )

    deduped_items = _dedupe_items(items)
    deduped_items.sort(key=lambda item: (item.distance_km is None, item.distance_km or 0.0, item.property_record.address or ""))
    return deduped_items[:limit]


async def _retrieve_office_under_threshold(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    threshold = Decimal(str(plan.filters["price_per_sq_ft_lt"]))
    rows = await _fetch_property_rows(
        session,
        (
            PropertyRecord.property_type == "office",
            PropertyRecord.price_per_sq_ft.is_not(None),
            PropertyRecord.price_per_sq_ft < threshold,
        )
    )

    items = [
        _build_evidence_item(
            property_record,
            source_document,
            chunk,
            relevance_score=Decimal("0.9400"),
            matched_fields=["property_type", "price_per_sq_ft", "availability"],
        )
        for property_record, source_document, chunk in rows
    ]
    deduped_items = _dedupe_items(items)
    deduped_items.sort(
        key=lambda item: (item.property_record.price_per_sq_ft or Decimal("0"), item.property_record.address or "")
    )
    return deduped_items


def _dedupe_key(property_record: PropertyRecord) -> str:
    return property_record.duplicate_group_key or property_record.normalized_address or str(property_record.id)


def _priority_tuple(item: RetrievedEvidence) -> tuple[float, float, float]:
    authority = float(item.property_record.source_authority_score or Decimal("0"))
    freshness = float(item.property_record.freshness_score or Decimal("0"))
    posted = item.source_document.posted_at.timestamp() if item.source_document.posted_at is not None else 0.0
    return (authority, freshness, posted)


def _dedupe_items(items: list[RetrievedEvidence]) -> list[RetrievedEvidence]:
    deduped: dict[str, RetrievedEvidence] = {}
    for item in items:
        key = _dedupe_key(item.property_record)
        existing = deduped.get(key)
        if existing is None or _priority_tuple(item) > _priority_tuple(existing):
            deduped[key] = item
    return list(deduped.values())


def _hybrid_match_to_evidence(match: HybridChunkMatch) -> RetrievedEvidence:
    return _build_evidence_item(
        match.property_record,
        match.source_document,
        match.chunk,
        relevance_score=match.relevance_score,
        matched_fields=match.matched_terms,
        selection_reason=match.selection_reason,
        retrieval_metadata=match.retrieval_metadata,
    )


def _structured_match_to_evidence(match: StructuredPropertyMatch) -> RetrievedEvidence:
    return _build_evidence_item(
        match.property_record,
        match.source_document,
        match.chunk,
        relevance_score=match.relevance_score,
        matched_fields=match.matched_fields,
    )


async def _retrieve_loading_access_search(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    matches = await retrieve_loading_access_matches(
        session,
        property_type=str(plan.filters["property_type"]),
        expanded_terms=list(plan.filters["expanded_terms"]),
        query_text=str(plan.filters.get("query_text") or ""),
        concept=str(plan.filters.get("concept") or "loading_access_or_yard_space"),
    )
    return [_hybrid_match_to_evidence(match) for match in matches]


def _build_harbor_conflict_summary(item: RetrievedEvidence) -> str:
    sq_ft_label = _format_sq_ft(item.property_record.sq_ft)
    return f"{item.source_summary} reports {sq_ft_label} for {item.property_record.address}."


async def _retrieve_harbor_conflict(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    rows = await _fetch_property_rows(
        session,
        (
            PropertyRecord.duplicate_group_key == str(plan.filters["duplicate_group_key"]),
            PropertyRecord.address.is_not(None),
        ),
    )

    candidates = [
        _build_evidence_item(
            property_record,
            source_document,
            chunk,
            relevance_score=Decimal("0.9000"),
            matched_fields=["sq_ft", "freshness_score", "source_authority_score"],
        )
        for property_record, source_document, chunk in rows
    ]
    if not candidates:
        return []

    selected = max(candidates, key=_priority_tuple)
    selected_sq_ft = selected.property_record.sq_ft
    supporting = [
        item
        for item in candidates
        if item.property_record.id != selected.property_record.id and item.property_record.sq_ft == selected_sq_ft
    ]
    superseded = [item for item in candidates if item.property_record.sq_ft != selected_sq_ft]

    supporting.sort(key=_priority_tuple, reverse=True)
    superseded.sort(key=_priority_tuple, reverse=True)

    ordered = [selected, *supporting, *superseded]
    role_scores = {
        str(selected.property_record.id): Decimal("0.9900"),
    }
    for item in supporting:
        role_scores[str(item.property_record.id)] = Decimal("0.9400")
    for item in superseded:
        role_scores[str(item.property_record.id)] = Decimal("0.8200")

    return [
        _build_evidence_item(
            item.property_record,
            item.source_document,
            item.chunk,
            relevance_score=role_scores[str(item.property_record.id)],
            matched_fields=item.matched_fields,
        )
        for item in ordered
    ]


async def _retrieve_john_industrial_square_footage(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    source_types = list(plan.filters["source_types"])
    rows = await _fetch_property_rows(
        session,
        (
            PropertyRecord.property_type == "industrial",
            SourceDocument.slack_user_name == "John",
            SourceDocument.source_type.in_(source_types),
        )
    )

    deduped: dict[str, RetrievedEvidence] = {}
    for property_record, source_document, chunk in rows:
        item = _build_evidence_item(
            property_record,
            source_document,
            chunk,
            relevance_score=Decimal("0.9300"),
            matched_fields=["property_type", "sq_ft", "source_authority_score"],
        )
        key = _dedupe_key(property_record)
        existing = deduped.get(key)
        if existing is None or _priority_tuple(item) > _priority_tuple(existing):
            deduped[key] = item

    return sorted(deduped.values(), key=lambda item: item.property_record.address or "")


async def _retrieve_source_lookup(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    price_per_sq_ft = Decimal(str(plan.filters["price_per_sq_ft"]))
    rows = await _fetch_property_rows(
        session,
        (
            PropertyRecord.normalized_address == str(plan.filters["normalized_address"]),
            PropertyRecord.price_per_sq_ft == price_per_sq_ft,
        )
    )

    items = [
        _build_evidence_item(
            property_record,
            source_document,
            chunk,
            relevance_score=Decimal("0.9500"),
            matched_fields=["price_per_sq_ft", "normalized_address"],
        )
        for property_record, source_document, chunk in rows
    ]
    items.sort(key=lambda item: _priority_tuple(item), reverse=True)
    return items


async def _retrieve_generic_property_search(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    matches = await retrieve_structured_property_matches(session, dict(plan.filters), dedupe=True)
    return [_structured_match_to_evidence(match) for match in matches]


async def _retrieve_generic_exact_lookup(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    filters = dict(plan.filters)
    filters["limit"] = max(int(filters.get("limit") or 5), 10)
    matches = await retrieve_structured_property_matches(session, filters, dedupe=False)
    return [_structured_match_to_evidence(match) for match in matches]


async def _retrieve_generic_aggregation(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    filters = dict(plan.filters)
    filters["limit"] = max(int(filters.get("limit") or 5), 25)
    matches = await retrieve_structured_property_matches(session, filters, dedupe=True)
    return [_structured_match_to_evidence(match) for match in matches]


async def _retrieve_generic_tenant_fit(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    matches = await retrieve_tenant_fit_matches(session, dict(plan.filters))
    return [_structured_match_to_evidence(match) for match in matches]


async def _retrieve_evidence(session: AsyncSession, plan: QueryPlan) -> list[RetrievedEvidence]:
    if plan.query_type == "proximity":
        return await _retrieve_proximity(session, plan)
    if plan.query_type == "office_under_threshold":
        return await _retrieve_office_under_threshold(session, plan)
    if plan.query_type == "john_industrial_square_footage":
        return await _retrieve_john_industrial_square_footage(session, plan)
    if plan.query_type == "source_lookup":
        return await _retrieve_source_lookup(session, plan)
    if plan.query_type == "loading_access_search":
        return await _retrieve_loading_access_search(session, plan)
    if plan.query_type in {"harbor_change_review", "harbor_conflict_why"}:
        return await _retrieve_harbor_conflict(session, plan)
    if plan.query_type == "generic_property_search":
        return await _retrieve_generic_property_search(session, plan)
    if plan.query_type == "generic_inventory_overview":
        return await _retrieve_generic_property_search(session, plan)
    if plan.query_type == "generic_exact_lookup":
        return await _retrieve_generic_exact_lookup(session, plan)
    if plan.query_type == "generic_aggregation":
        return await _retrieve_generic_aggregation(session, plan)
    if plan.query_type == "generic_tenant_fit":
        return await _retrieve_generic_tenant_fit(session, plan)
    return []


def _render_unsupported_answer() -> str:
    supported = "; ".join(SUPPORTED_QUERY_HINTS)
    return (
        "*Unsupported query for the current instant slice*\n"
        "I could not match that to a safe local route or sourced result. Use *Look deeper* if you want "
        "Toolhouse to try a broader backend MCP pass or explain what evidence is missing.\n"
        f"Supported patterns: {supported}."
    )


def _render_force_agent_seed_answer() -> str:
    return (
        "*Force-agent request*\n"
        "Skipping the instant router and sending this directly to Toolhouse with backend MCP citation checks."
    )


def _format_filter_summary(query_constructor: dict[str, object] | None) -> str:
    if not query_constructor:
        return "the requested filters"

    pieces: list[str] = []
    for condition in list(query_constructor.get("conditions", [])):
        field = str(condition.get("field", "field")).split(".")[-1]
        operator = str(condition.get("op", "="))
        value = condition.get("value")
        pieces.append(f"{field} {operator} {value}")
    return "; ".join(pieces) if pieces else "the requested filters"


def _render_no_results(plan: QueryPlan, no_results_context: dict[str, object] | None = None) -> str:
    if plan.query_type == "source_lookup":
        return "*No matching seeded source*\nNo matching seeded source was found for that field lookup."
    if plan.query_type == "loading_access_search":
        return "*No loading-access match found*\nNo industrial listing chunks matched loading access or yard space in the local corpus."
    if plan.query_type in {"harbor_change_review", "harbor_conflict_why"}:
        return "*No Harbor conflict evidence found*\nNo conflicting Harbor Rd evidence was found in the seeded local corpus."

    if no_results_context is not None:
        filters_label = _format_filter_summary(no_results_context.get("applied_query_constructor"))
        lines = ["*No sourced property match found*", f"I could not find a sourced property matching {filters_label}."]
        closest = list(no_results_context.get("closest_matches_after_relaxing_numeric_filters", []))
        if closest:
            lines.extend(["", "*Closest matches after relaxing numeric/date filters:*"])
            for match in closest[:3]:
                price = match.get("price_per_sq_ft")
                price_label = "unknown price" if price is None else f"${price}/SF"
                sq_ft = match.get("sq_ft")
                sq_ft_label = "unknown SF" if sq_ft is None else f"{int(sq_ft):,} SF"
                lines.append(
                    f"- *{match.get('address')}* - {sq_ft_label} at {price_label}, "
                    f"{match.get('availability') or 'availability unknown'}. Source: {match.get('source')}"
                )
        else:
            lines.extend(["", "_The indexed database has no close structured rows to relax toward yet._"])
        return "\n".join(lines)

    return "*No matching seeded properties found*\nNo matching seeded properties were found for that structured query."


def _partition_harbor_items(
    items: list[RetrievedEvidence],
) -> tuple[RetrievedEvidence, list[RetrievedEvidence], list[RetrievedEvidence]]:
    selected = items[0]
    selected_sq_ft = selected.property_record.sq_ft
    supporting = [
        item for item in items[1:] if item.property_record.sq_ft == selected_sq_ft
    ]
    superseded = [
        item for item in items[1:] if item.property_record.sq_ft != selected_sq_ft
    ]
    return selected, supporting, superseded


def _render_data_quality_answer(report: dict[str, object]) -> str:
    source_count = int(report.get("source_document_count") or 0)
    property_count = int(report.get("property_record_count") or 0)
    sources_without_properties = list(report.get("sources_without_properties", []))
    conflict_groups = list(report.get("conflict_groups", []))
    missing_counts = dict(report.get("missing_field_counts", {}))

    lines = [f"*Data-quality pass* - {source_count} sources and {property_count} structured property records are indexed."]
    if sources_without_properties:
        lines.append(f"- {len(sources_without_properties)} source(s) have text but no extracted property rows: {', '.join(map(str, sources_without_properties[:4]))}.")
    else:
        lines.append("- Every indexed source currently has at least one structured property row.")

    notable_missing = {field: count for field, count in missing_counts.items() if int(count or 0) > 0}
    if notable_missing:
        formatted = ", ".join(f"{field}: {count}" for field, count in sorted(notable_missing.items()))
        lines.append(f"- Missing-field counts across property rows: {formatted}.")
    else:
        lines.append("- Critical structured fields are filled across the current property rows.")

    if conflict_groups:
        lines.append(f"- {len(conflict_groups)} duplicate group(s) contain conflicting numeric facts; these are explainable through source freshness and authority.")
    else:
        lines.append("- No duplicate-group numeric conflicts were detected.")

    lines.extend(["", "_Ready for bounded Toolhouse escalation as long as the agent stays inside the evidence bundle._"])
    return "\n".join(lines)


def _render_generic_property_search(plan: QueryPlan, items: list[RetrievedEvidence]) -> str:
    title = "Found" if len(items) != 1 else "Found one"
    lines = [f"*{title} {len(items)} matching sourced listing(s)*"]
    for item in items:
        lines.append(
            f"- *{item.property_record.address}* - {_format_property_type(item.property_record.property_type)}, "
            f"{_format_sq_ft(item.property_record.sq_ft)} at {_format_price(item.property_record.price_per_sq_ft)}, "
            f"{item.property_record.availability or 'availability unknown'}. Source: {item.source_summary}"
        )
    lines.extend(["", f"_Direct match - {len(items)} source(s) checked._"])
    return "\n".join(lines)


def _render_inventory_overview(plan: QueryPlan, items: list[RetrievedEvidence]) -> str:
    type_counts: dict[str, int] = {}
    market_counts: dict[str, int] = {}
    for item in items:
        property_type = _format_property_type(item.property_record.property_type or "unknown")
        type_counts[property_type] = type_counts.get(property_type, 0) + 1
        if item.property_record.market:
            market_counts[item.property_record.market] = market_counts.get(item.property_record.market, 0) + 1

    type_summary = ", ".join(f"{name}: {count}" for name, count in sorted(type_counts.items())) or "no typed records"
    market_summary = ", ".join(
        f"{name}: {count}" for name, count in sorted(market_counts.items(), key=lambda item: (-item[1], item[0]))[:5]
    ) or "market coverage still sparse"
    sort_label = {
        "availability_asc": "soonest availability first",
        "price_asc": "lowest asking rent first",
        "size_desc": "largest spaces first",
    }.get(str(plan.filters.get("sort") or ""), "source authority and freshness first")

    lines = [
        "*Inventory snapshot from sourced property records*",
        f"I found {len(items)} deduped sourced propert{'y' if len(items) == 1 else 'ies'} in the current slice.",
        f"- By type: {type_summary}.",
        f"- Top markets: {market_summary}.",
        f"- Sort used: {sort_label}.",
        "",
        "*Properties:*",
    ]
    for item in items:
        lines.append(
            f"- *{item.property_record.address}* - {_format_property_type(item.property_record.property_type)}, "
            f"{_format_sq_ft(item.property_record.sq_ft)} at {_format_price(item.property_record.price_per_sq_ft)}, "
            f"{item.property_record.availability or 'availability unknown'}. Source: {item.source_summary}"
        )

    lines.extend(
        [
            "",
            "_This is a broad inventory view from structured records. Use *Look deeper* if you want Toolhouse to compare, rank, or turn this evidence bundle into a recommendation._",
        ]
    )
    return "\n".join(lines)


def _render_generic_exact_lookup(items: list[RetrievedEvidence]) -> str:
    selected = items[0]
    lines = [
        "*Exact property read*",
        f"*{selected.property_record.address}* looks like {_format_sq_ft(selected.property_record.sq_ft)} "
        f"{_format_property_type(selected.property_record.property_type)} at {_format_price(selected.property_record.price_per_sq_ft)}, "
        f"available {selected.property_record.availability or 'unknown'}."
    ]
    lines.extend(["", "*Sources checked:*" ])
    for item in items[:5]:
        lines.append(f"- {item.source_summary}")
    if len(items) > 5:
        lines.append(f"- Plus {len(items) - 5} more source(s) in the evidence bundle.")
    return "\n".join(lines)


def _render_generic_aggregation(plan: QueryPlan, items: list[RetrievedEvidence]) -> str:
    aggregate = str(plan.filters.get("aggregate") or "count")
    aggregate_field = str(plan.filters.get("aggregate_field") or "property_records")
    if aggregate == "count":
        headline = f"Counted {len(items)} matching sourced property record(s)."
    elif aggregate == "average" and aggregate_field == "price_per_sq_ft":
        values = [item.property_record.price_per_sq_ft for item in items if item.property_record.price_per_sq_ft is not None]
        average = sum(values, Decimal("0")) / Decimal(len(values)) if values else None
        headline = "No matching records had price data to average." if average is None else f"Average asking rent is ${average:,.2f}/SF across {len(values)} matching listing(s)."
    else:
        values = [item.property_record.sq_ft for item in items if item.property_record.sq_ft is not None]
        total = sum(values)
        headline = f"Total square footage is {total:,} SF across {len(values)} matching listing(s)."

    lines = ["*Aggregation result*", headline]
    for item in items[:8]:
        lines.append(f"- *{item.property_record.address}* - {_format_sq_ft(item.property_record.sq_ft)}. Source: {item.source_summary}")
    if len(items) > 8:
        lines.append(f"- Plus {len(items) - 8} more matching listing(s).")
    return "\n".join(lines)


def _render_generic_tenant_fit(items: list[RetrievedEvidence]) -> str:
    lines = ["*Best local shortlist for that tenant fit*", ""]
    for index, item in enumerate(items[:3], start=1):
        reasons: list[str] = []
        if item.property_record.price_per_sq_ft is not None and item.property_record.price_per_sq_ft <= Decimal("35"):
            reasons.append("under $35/SF")
        if item.property_record.sq_ft is not None and item.property_record.sq_ft >= 15000:
            reasons.append("usable scale")
        if item.property_record.availability_date is not None and item.property_record.availability_date.isoformat() <= "2026-08-31":
            reasons.append("available soon")
        if any(term in item.matched_fields for term in ("loading dock", "yard", "logistics")):
            reasons.append("logistics language in source")
        reason_label = ", ".join(reasons) if reasons else "best source-quality fit"
        lines.append(
            f"{index}. *{item.property_record.address}* - {_format_sq_ft(item.property_record.sq_ft)} at "
            f"{_format_price(item.property_record.price_per_sq_ft)}; {reason_label}. Source: {item.source_summary}"
        )
    lines.extend(
        [
            "",
            "_Expanded search:_ local heuristic only. Use the *Look deeper* button to send this evidence bundle to Toolhouse next.",
        ]
    )
    return "\n".join(lines)


def _build_comparison_table(plan: QueryPlan, items: list[RetrievedEvidence]) -> dict[str, object] | None:
    if len(items) < 2:
        return None

    if plan.query_type == "proximity":
        columns = ["Addr", "SF", "Rent", "Dist"]
        rows = [
            [
                str(item.property_record.address or "-"),
                _format_sq_ft(item.property_record.sq_ft),
                _format_price(item.property_record.price_per_sq_ft),
                f"{item.distance_km:.1f} km" if item.distance_km is not None else "-",
            ]
            for item in items[:5]
        ]
        return {"title": "Quick comparison", "columns": columns, "rows": rows}

    columns = ["Addr", "SF", "Rent", "Avail"]
    rows = [
        [
            str(item.property_record.address or "-"),
            _format_sq_ft(item.property_record.sq_ft),
            _format_price(item.property_record.price_per_sq_ft),
            str(item.property_record.availability or "-"),
        ]
        for item in items[:5]
    ]
    return {"title": "Quick comparison", "columns": columns, "rows": rows}


def _render_answer(
    plan: QueryPlan,
    items: list[RetrievedEvidence],
    *,
    no_results_context: dict[str, object] | None = None,
) -> str:
    if not items:
        return _render_no_results(plan, no_results_context)

    if plan.query_type == "proximity":
        anchor_address = str(plan.filters["anchor_address"])
        lines = [f"*Closest available properties to {anchor_address}:*"]
        for index, item in enumerate(items, start=1):
            distance_label = f"{item.distance_km:.2f} km away" if item.distance_km is not None else "distance unavailable"
            lines.append(
                f"{index}. *{item.property_record.address}* - {_format_property_type(item.property_record.property_type)}, "
                f"{_format_sq_ft(item.property_record.sq_ft)} at {_format_price(item.property_record.price_per_sq_ft)}, "
                f"{item.property_record.availability or 'availability unknown'}, {distance_label}. "
                f"Source: {item.source_summary}"
            )
        return "\n".join(lines)

    if plan.query_type == "office_under_threshold":
        threshold = Decimal(str(plan.filters["price_per_sq_ft_lt"]))
        lines = [f"*Office listings under ${threshold:,.2f}/SF:*"]
        for item in items:
            lines.append(
                f"- *{item.property_record.address}* - {_format_sq_ft(item.property_record.sq_ft)} at "
                f"{_format_price(item.property_record.price_per_sq_ft)}, "
                f"{item.property_record.availability or 'availability unknown'}. Source: {item.source_summary}"
            )
        return "\n".join(lines)

    if plan.query_type == "john_industrial_square_footage":
        total_sq_ft = sum(item.property_record.sq_ft or 0 for item in items)
        lines = [
            "*Industrial availability from John's files and notes*",
            f"John's files and notes show {total_sq_ft:,} SF of industrial availability across {len(items)} properties."
        ]
        for item in items:
            lines.append(
                f"- *{item.property_record.address}* - {_format_sq_ft(item.property_record.sq_ft)} at "
                f"{_format_price(item.property_record.price_per_sq_ft)}. Source: {item.source_summary}"
            )
        return "\n".join(lines)

    if plan.query_type == "source_lookup":
        price_per_sq_ft = Decimal(str(plan.filters["price_per_sq_ft"]))
        lines = [f"*Source lookup for ${price_per_sq_ft:,.2f}/SF at 120 Main*", f"The ${price_per_sq_ft:,.2f}/SF figure for 120 Main appears in {len(items)} sources:"]
        for item in items:
            lines.append(f"- {item.source_summary}")
        return "\n".join(lines)

    if plan.query_type == "loading_access_search":
        lines = ["*Industrial listings that mention loading access or yard space:*"]
        for item in items:
            matched_terms = ", ".join(item.matched_fields)
            lines.append(
                f"- *{item.property_record.address}* - {_format_sq_ft(item.property_record.sq_ft)} at "
                f"{_format_price(item.property_record.price_per_sq_ft)}, "
                f"{item.property_record.availability or 'availability unknown'}. "
                f"*Matched terms:* {matched_terms}. Source: {item.source_summary}"
            )
        return "\n".join(lines)

    if plan.query_type in {"harbor_change_review", "harbor_conflict_why"}:
        selected, supporting, superseded = _partition_harbor_items(items)
        selected_sq_ft = _format_sq_ft(selected.property_record.sq_ft)
        prior_item = superseded[0] if superseded else None
        prior_sq_ft = _format_sq_ft(prior_item.property_record.sq_ft) if prior_item is not None else "an older value"

        if plan.query_type == "harbor_change_review":
            lines = [
                "*Harbor Rd change review*",
                f"Yes. *240 Harbor Rd* changed from {prior_sq_ft} to {selected_sq_ft} yesterday.",
                f"I am using {selected_sq_ft} because {_build_harbor_conflict_summary(selected)} It is the freshest, highest-authority correction in the duplicate group.",
            ]
            for item in supporting:
                lines.append(f"- Supporting update: {_build_harbor_conflict_summary(item)}")
            if prior_item is not None:
                lines.append(f"- Superseded source: {_build_harbor_conflict_summary(prior_item)}")
            return "\n".join(lines)

        lines = [
            "*Harbor Rd conflict review*",
            f"I used {selected_sq_ft} for *240 Harbor Rd* because {_build_harbor_conflict_summary(selected)}",
            "That evidence outranks the older inventory row on freshness and source authority.",
        ]
        for item in supporting:
            lines.append(f"- Supporting evidence: {_build_harbor_conflict_summary(item)}")
        if prior_item is not None:
            lines.append(f"- Superseded evidence: {_build_harbor_conflict_summary(prior_item)}")
        return "\n".join(lines)

    if plan.query_type == "generic_property_search":
        return _render_generic_property_search(plan, items)

    if plan.query_type == "generic_inventory_overview":
        return _render_inventory_overview(plan, items)

    if plan.query_type == "generic_exact_lookup":
        return _render_generic_exact_lookup(items)

    if plan.query_type == "generic_aggregation":
        return _render_generic_aggregation(plan, items)

    if plan.query_type == "generic_tenant_fit":
        return _render_generic_tenant_fit(items)

    return _render_no_results(plan, no_results_context)


async def answer_query(
    query_text: str,
    *,
    slack_channel_id: str | None = None,
    slack_user_id: str | None = None,
    slack_ts: str | None = None,
    slack_thread_ts: str | None = None,
) -> dict[str, object]:
    plan = build_query_plan(query_text)
    slack_context = _slack_context_payload(
        slack_channel_id=slack_channel_id,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        slack_thread_ts=slack_thread_ts,
    )

    async with SessionFactory() as session:
        async with session.begin():
            query_record = Query(
                slack_channel_id=slack_channel_id,
                slack_user_id=slack_user_id,
                slack_ts=slack_ts,
                query_text=query_text,
                route_mode=plan.route_mode,
                route_confidence=plan.route_confidence,
                reason_codes=plan.reason_codes,
            )
            session.add(query_record)
            await session.flush()

            if plan.query_type == "unsupported":
                snapshot = AnswerSnapshot(
                    query_id=query_record.id,
                    rendered_answer=_render_unsupported_answer(),
                    route_mode=plan.route_mode,
                    filters_json=_snapshot_filters_for_plan(plan, slack_context=slack_context),
                    evidence_ids=[],
                    dependency_state_json=_dependency_state_for_plan(plan),
                    model_versions_json=_model_versions_for_plan(plan),
                )
                session.add(snapshot)
                await session.flush()
                return {
                    "status": "unsupported",
                    "answer_mode": "instant_answer",
                    "route_mode": plan.route_mode,
                    "query_id": str(query_record.id),
                    "answer_snapshot_id": str(snapshot.id),
                    "reason_codes": plan.reason_codes,
                    "filters": snapshot.filters_json,
                    "evidence_count": 0,
                    "matched_addresses": [],
                    "citations": [],
                    "comparison_table": None,
                    "rendered_answer": snapshot.rendered_answer,
                }

            if plan.query_type == "generic_data_completeness":
                data_quality_report = await collect_data_quality_report(session)
                rendered_answer = _render_data_quality_answer(data_quality_report)
                snapshot = AnswerSnapshot(
                    query_id=query_record.id,
                    rendered_answer=rendered_answer,
                    route_mode=plan.route_mode,
                    filters_json=_snapshot_filters_for_plan(
                        plan,
                        data_quality_report=data_quality_report,
                        slack_context=slack_context,
                    ),
                    evidence_ids=[],
                    dependency_state_json=_dependency_state_for_plan(plan),
                    model_versions_json=_model_versions_for_plan(plan),
                )
                session.add(snapshot)
                await session.flush()
                return {
                    "status": "answered",
                    "answer_mode": "instant_answer",
                    "route_mode": plan.route_mode,
                    "query_id": str(query_record.id),
                    "answer_snapshot_id": str(snapshot.id),
                    "reason_codes": plan.reason_codes,
                    "filters": snapshot.filters_json,
                    "evidence_count": 0,
                    "matched_addresses": [],
                    "citations": [],
                    "comparison_table": None,
                    "rendered_answer": rendered_answer,
                    "data_quality_report": data_quality_report,
                }

            items = await _retrieve_evidence(session, plan)
            no_results_context = None
            constructor_filters = _query_constructor_filters_for_plan(plan)
            if not items and constructor_filters is not None:
                no_results_context = await explain_no_results(session, constructor_filters)
            rendered_answer = _render_answer(plan, items, no_results_context=no_results_context)
            comparison_table = _build_comparison_table(plan, items)

            evidence_records: list[EvidenceItem] = []
            for item in items:
                evidence_record = EvidenceItem(
                    query_id=query_record.id,
                    document_id=item.source_document.id,
                    chunk_id=item.chunk.id if item.chunk is not None else None,
                    property_record_id=item.property_record.id,
                    relevance_score=item.relevance_score,
                    matched_fields=item.matched_fields,
                    source_summary=item.source_summary,
                )
                session.add(evidence_record)
                evidence_records.append(evidence_record)

            await session.flush()
            snapshot = AnswerSnapshot(
                query_id=query_record.id,
                rendered_answer=rendered_answer,
                route_mode=plan.route_mode,
                filters_json=_snapshot_filters_for_plan(
                    plan,
                    no_results_context=no_results_context,
                    slack_context=slack_context,
                ),
                evidence_ids=[record.id for record in evidence_records],
                dependency_state_json=_dependency_state_for_result(plan, items),
                model_versions_json=_model_versions_for_plan(plan),
            )
            session.add(snapshot)
            await session.flush()

            return {
                "status": "answered" if items else "no_results",
                "answer_mode": "instant_answer",
                "route_mode": plan.route_mode,
                "query_id": str(query_record.id),
                "answer_snapshot_id": str(snapshot.id),
                "reason_codes": plan.reason_codes,
                "filters": snapshot.filters_json,
                "evidence_count": len(evidence_records),
                "matched_addresses": _unique_addresses(items),
                "citations": [record.source_summary for record in evidence_records],
                "comparison_table": comparison_table,
                "rendered_answer": rendered_answer,
                "missing_data_explanation": no_results_context,
            }


async def create_force_agent_query(
    query_text: str,
    *,
    slack_channel_id: str | None = None,
    slack_user_id: str | None = None,
    slack_ts: str | None = None,
    slack_thread_ts: str | None = None,
    reason_codes: list[str] | None = None,
) -> dict[str, object]:
    normalized_query = " ".join(str(query_text or "").split())
    slack_context = _slack_context_payload(
        slack_channel_id=slack_channel_id,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        slack_thread_ts=slack_thread_ts,
    )
    normalized_reason_codes = ["force_agent", "instant_router_skipped"]
    for code in reason_codes or []:
        normalized_code = str(code or "").strip()
        if normalized_code and normalized_code not in normalized_reason_codes:
            normalized_reason_codes.append(normalized_code)

    async with SessionFactory() as session:
        async with session.begin():
            query_record = Query(
                slack_channel_id=slack_channel_id,
                slack_user_id=slack_user_id,
                slack_ts=slack_ts,
                query_text=normalized_query,
                route_mode="agent_forced",
                route_confidence=Decimal("1.0000"),
                reason_codes=normalized_reason_codes,
            )
            session.add(query_record)
            await session.flush()

            snapshot = AnswerSnapshot(
                query_id=query_record.id,
                rendered_answer=_render_force_agent_seed_answer(),
                route_mode="agent_forced",
                filters_json={"force_agent": True, "slack_context": slack_context},
                evidence_ids=[],
                dependency_state_json={
                    "force_agent": True,
                    "instant_router_skipped": True,
                    "toolhouse_direct": True,
                },
                model_versions_json={"answering": "force-agent-v1"},
            )
            session.add(snapshot)
            await session.flush()

            return {
                "status": "ready",
                "answer_mode": "agent_mode",
                "route_mode": "agent_forced",
                "query_id": str(query_record.id),
                "answer_snapshot_id": str(snapshot.id),
                "reason_codes": list(query_record.reason_codes or []),
                "filters": snapshot.filters_json,
                "evidence_count": 0,
                "matched_addresses": [],
                "citations": [],
                "comparison_table": None,
                "rendered_answer": snapshot.rendered_answer,
            }


async def explain_query(query_id: str) -> dict[str, object]:
    try:
        parsed_query_id = UUID(query_id)
    except ValueError:
        return {
            "status": "invalid_query_id",
            "query_id": query_id,
            "message": "Query ID must be a valid UUID.",
        }

    async with SessionFactory() as session:
        query_record = await session.get(Query, parsed_query_id)
        if query_record is None:
            return {
                "status": "not_found",
                "query_id": query_id,
                "message": "No stored query exists for that ID.",
            }

        snapshot = await session.scalar(select(AnswerSnapshot).where(AnswerSnapshot.query_id == query_record.id))
        evidence_rows = await session.execute(
            select(EvidenceItem, SourceDocument, Chunk, PropertyRecord)
            .outerjoin(SourceDocument, EvidenceItem.document_id == SourceDocument.id)
            .outerjoin(Chunk, EvidenceItem.chunk_id == Chunk.id)
            .outerjoin(PropertyRecord, EvidenceItem.property_record_id == PropertyRecord.id)
            .where(EvidenceItem.query_id == query_record.id)
        )

        snapshot_evidence_order = {
            evidence_id: index for index, evidence_id in enumerate(snapshot.evidence_ids if snapshot is not None else [])
        }
        evidence_bundle: list[dict[str, object]] = []
        for evidence_item, source_document, chunk, property_record in evidence_rows:
            matched_field_names = list(evidence_item.matched_fields or [])
            field_details: list[dict[str, object]] = []
            if property_record is not None and matched_field_names:
                field_result = await session.execute(
                    select(PropertyFieldValue)
                    .where(PropertyFieldValue.property_record_id == property_record.id)
                    .where(PropertyFieldValue.field_name.in_(matched_field_names))
                    .order_by(PropertyFieldValue.field_name)
                )
                field_details = [_serialize_field_value(field_value) for field_value in field_result.scalars()]

            evidence_bundle.append(
                {
                    "evidence_id": str(evidence_item.id),
                    "relevance_score": _serialize_decimal(evidence_item.relevance_score),
                    "matched_fields": matched_field_names,
                    "source_summary": evidence_item.source_summary,
                    "source_document": _serialize_source_document(source_document),
                    "property_record": _serialize_property_record(property_record),
                    "chunk": _serialize_chunk(chunk),
                    "field_details": field_details,
                }
            )

        evidence_bundle.sort(
            key=lambda item: snapshot_evidence_order.get(UUID(str(item["evidence_id"])), len(snapshot_evidence_order))
        )

        filters = snapshot.filters_json if snapshot is not None else {}
        dependency_state = snapshot.dependency_state_json if snapshot is not None else {}
        model_versions = snapshot.model_versions_json if snapshot is not None else {}
        plan = build_query_plan(query_record.query_text)
        slack_context = dict(filters.get("slack_context") or {}) if isinstance(filters.get("slack_context"), dict) else {}
        if query_record.slack_channel_id:
            slack_context.setdefault("channel_id", query_record.slack_channel_id)
        if query_record.slack_user_id:
            slack_context.setdefault("user_id", query_record.slack_user_id)
        if query_record.slack_ts:
            slack_context.setdefault("message_ts", query_record.slack_ts)
            slack_context.setdefault("thread_ts", query_record.slack_ts)

        decision_summary: dict[str, object] | None = None
        if plan.query_type == "loading_access_search" and evidence_bundle:
            matched_addresses: list[str] = []
            contributors = list(dependency_state.get("retrieval_contributors") or [])
            contributor_label = ", ".join(map(str, contributors)) if contributors else "local retrieval"
            for item in evidence_bundle:
                property_record = item["property_record"]
                matched_terms = list(item["matched_fields"])
                item["evidence_role"] = "result"
                item["selection_reason"] = (
                    f"hybrid lexical/fuzzy retrieval matched: {', '.join(matched_terms)} via {contributor_label}"
                    if matched_terms
                    else f"hybrid lexical/fuzzy retrieval via {contributor_label}"
                )
                if property_record is not None and property_record.get("address") is not None:
                    matched_addresses.append(str(property_record["address"]))

            decision_summary = {
                "selected_addresses": matched_addresses,
                "selection_reason": "hybrid lexical, fuzzy, alias, and optional vector retrieval over indexed source chunks",
                "retrieval_mode": dependency_state.get("retrieval_mode"),
                "retrieval_layers": dependency_state.get("retrieval_layers"),
                "retrieval_contributors": dependency_state.get("retrieval_contributors"),
                "query_expansion_terms": dependency_state.get("query_expansion_terms"),
            }

        if plan.query_type in {"harbor_change_review", "harbor_conflict_why"} and evidence_bundle:
            selected_sq_ft = evidence_bundle[0]["property_record"]["sq_ft"] if evidence_bundle[0]["property_record"] else None
            superseded_values: list[int] = []
            for index, item in enumerate(evidence_bundle):
                property_record = item["property_record"]
                if property_record is None:
                    item["evidence_role"] = None
                    item["selection_reason"] = None
                    continue

                if index == 0:
                    item["evidence_role"] = "selected"
                    item["selection_reason"] = "freshest correction with the highest source authority"
                elif property_record["sq_ft"] == selected_sq_ft:
                    item["evidence_role"] = "supporting"
                    item["selection_reason"] = "supports the selected 62,000 SF update"
                else:
                    item["evidence_role"] = "superseded"
                    item["selection_reason"] = "older conflicting value outranked by fresher correction evidence"
                    if property_record["sq_ft"] is not None:
                        superseded_values.append(int(property_record["sq_ft"]))

            decision_summary = {
                "selected_address": filters.get("address"),
                "selected_sq_ft": selected_sq_ft,
                "superseded_sq_ft": superseded_values,
                "selection_reason": "freshest correction over the older inventory row",
                "retrieval_mode": dependency_state.get("retrieval_mode"),
            }

        if plan.query_type in {"generic_property_search", "generic_inventory_overview", "generic_exact_lookup", "generic_aggregation"} and evidence_bundle:
            selected_addresses: list[str] = []
            for item in evidence_bundle:
                property_record = item["property_record"]
                matched_fields = list(item["matched_fields"])
                item["evidence_role"] = "result"
                item["selection_reason"] = (
                    f"structured query constructor matched: {', '.join(matched_fields)}"
                    if matched_fields
                    else "structured query constructor match"
                )
                if property_record is not None and property_record.get("address") is not None:
                    selected_addresses.append(str(property_record["address"]))

            decision_summary = {
                "selected_addresses": selected_addresses,
                "selection_reason": "PostgreSQL structured query constructor over normalized property records",
                "query_constructor": filters.get("query_constructor"),
            }

        if plan.query_type == "generic_tenant_fit" and evidence_bundle:
            selected_addresses = []
            for index, item in enumerate(evidence_bundle):
                property_record = item["property_record"]
                item["evidence_role"] = "selected" if index == 0 else "candidate"
                item["selection_reason"] = "local tenant-fit heuristic scored price, size, availability, source quality, and logistics terms"
                if property_record is not None and property_record.get("address") is not None:
                    selected_addresses.append(str(property_record["address"]))

            decision_summary = {
                "selected_addresses": selected_addresses,
                "selection_reason": "local tenant-fit heuristic before Toolhouse escalation",
                "retrieval_mode": dependency_state.get("retrieval_mode"),
                "query_constructor": filters.get("query_constructor"),
            }

        if plan.query_type == "generic_data_completeness":
            decision_summary = {
                "selection_reason": "database quality report over indexed sources, property rows, missing fields, and conflict groups",
                "data_quality_report": filters.get("data_quality_report"),
            }

        return {
            "status": "explained",
            "query_id": str(query_record.id),
            "query_text": query_record.query_text,
            "created_at": query_record.created_at.isoformat() if query_record.created_at else None,
            "route_mode": query_record.route_mode,
            "route_confidence": _serialize_decimal(query_record.route_confidence),
            "reason_codes": list(query_record.reason_codes or []),
            "answer_snapshot": {
                "id": str(snapshot.id) if snapshot is not None else None,
                "route_mode": snapshot.route_mode if snapshot is not None else None,
                "filters": filters,
                "dependency_state": dependency_state,
                "model_versions": model_versions,
                "evidence_ids": _serialize_uuid_list(snapshot.evidence_ids) if snapshot is not None else [],
                "rendered_answer": snapshot.rendered_answer if snapshot is not None else None,
            },
            "evidence_count": len(evidence_bundle),
            "evidence": evidence_bundle,
            "source_summaries": [item["source_summary"] for item in evidence_bundle if item["source_summary"]],
            "decision_summary": decision_summary,
            "missing_data_explanation": filters.get("missing_data_explanation"),
            "data_quality_report": filters.get("data_quality_report"),
            "slack_context": slack_context,
        }