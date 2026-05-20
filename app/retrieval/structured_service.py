from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import Select, String, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Chunk, PropertyRecord, SourceDocument
from app.retrieval.spatial import get_postgis_status
from app.routing.query_constructor import DEMO_REFERENCE_DATE


@dataclass(frozen=True)
class StructuredPropertyMatch:
    property_record: PropertyRecord
    source_document: SourceDocument
    chunk: Chunk | None
    matched_fields: list[str]
    relevance_score: Decimal
    selection_reason: str


CRITICAL_PROPERTY_FIELDS = [
    "address",
    "property_type",
    "sq_ft",
    "price_per_sq_ft",
    "availability",
    "market",
    "geo",
    "status",
    "city",
    "locality",
    "neighborhood",
    "map_url",
    "additional_information",
]


def _as_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _parse_date(value: object) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def describe_query_constructor(filters: dict[str, object]) -> dict[str, object]:
    conditions: list[dict[str, object]] = []

    if filters.get("property_types"):
        conditions.append({"field": "property_records.property_type", "op": "in", "value": filters["property_types"]})
    if filters.get("address_terms"):
        conditions.append({"field": "property_records.normalized_address", "op": "contains_any", "value": filters["address_terms"]})
    if filters.get("uploader_names"):
        conditions.append({"field": "source_documents.slack_user_name", "op": "in", "value": filters["uploader_names"]})
    if filters.get("markets"):
        conditions.append({"field": "property_records.market", "op": "contains_any", "value": filters["markets"]})
    if filters.get("locations"):
        conditions.append({"field": "property_records.location_fields", "op": "contains_any", "value": filters["locations"]})
    if filters.get("statuses"):
        conditions.append({"field": "property_records.status", "op": "contains_any", "value": filters["statuses"]})
    if filters.get("usage_types"):
        conditions.append({"field": "property_records.usage_type", "op": "contains_any", "value": filters["usage_types"]})
    if filters.get("facing"):
        conditions.append({"field": "property_records.facing", "op": "contains_any", "value": filters["facing"]})
    if filters.get("furnishing_statuses"):
        conditions.append({"field": "property_records.furnishing_status", "op": "contains_any", "value": filters["furnishing_statuses"]})
    if filters.get("infrastructure_terms"):
        conditions.append({"field": "property_records.infrastructure", "op": "contains_any", "value": filters["infrastructure_terms"]})
    if filters.get("keywords") and filters.get("intent") != "tenant_fit":
        conditions.append({"field": "chunks.chunk_text", "op": "contains_any", "value": filters["keywords"]})
    if filters.get("price_per_sq_ft_lt") is not None:
        conditions.append({"field": "property_records.price_per_sq_ft", "op": "<", "value": filters["price_per_sq_ft_lt"]})
    if filters.get("price_per_sq_ft_gt") is not None:
        conditions.append({"field": "property_records.price_per_sq_ft", "op": ">", "value": filters["price_per_sq_ft_gt"]})
    if filters.get("sale_price_lt") is not None:
        conditions.append({"field": "property_records.sale_price", "op": "<", "value": filters["sale_price_lt"]})
    if filters.get("sale_price_gt") is not None:
        conditions.append({"field": "property_records.sale_price", "op": ">", "value": filters["sale_price_gt"]})
    if filters.get("cap_rate_gte") is not None:
        conditions.append({"field": "property_records.cap_rate", "op": ">=", "value": filters["cap_rate_gte"]})
    if filters.get("cap_rate_lte") is not None:
        conditions.append({"field": "property_records.cap_rate", "op": "<=", "value": filters["cap_rate_lte"]})
    if filters.get("sq_ft_gte") is not None:
        conditions.append({"field": "property_records.sq_ft", "op": ">=", "value": filters["sq_ft_gte"]})
    if filters.get("sq_ft_lte") is not None:
        conditions.append({"field": "property_records.sq_ft", "op": "<=", "value": filters["sq_ft_lte"]})
    if filters.get("clear_height_ft_gte") is not None:
        conditions.append({"field": "property_records.clear_height_ft", "op": ">=", "value": filters["clear_height_ft_gte"]})
    if filters.get("dock_doors_gte") is not None:
        conditions.append({"field": "property_records.dock_doors", "op": ">=", "value": filters["dock_doors_gte"]})
    if filters.get("trailer_parking_spaces_gte") is not None:
        conditions.append({"field": "property_records.trailer_parking_spaces", "op": ">=", "value": filters["trailer_parking_spaces_gte"]})
    if filters.get("parking_spaces_gte") is not None:
        conditions.append({"field": "property_records.parking_spaces", "op": ">=", "value": filters["parking_spaces_gte"]})
    if filters.get("availability_before") is not None:
        conditions.append({"field": "property_records.availability_date", "op": "<=", "value": filters["availability_before"]})
    if filters.get("require_immediate"):
        conditions.append({"field": "property_records.availability", "op": "immediate_or_now", "value": True})
    if filters.get("requires_coordinates"):
        conditions.append({"field": "property_records.geo_lat_lng", "op": "present", "value": True})

    return {
        "base_table": "property_records",
        "joins": ["source_documents", "chunks"],
        "conditions": conditions,
        "rerank_terms": filters.get("keywords", []) if filters.get("intent") == "tenant_fit" else [],
        "sort": filters.get("sort"),
        "limit": filters.get("limit", 5),
    }


def _build_conditions(filters: dict[str, object]) -> list[object]:
    conditions: list[object] = []
    property_types = [str(value) for value in filters.get("property_types") or []]
    if property_types:
        conditions.append(PropertyRecord.property_type.in_(property_types))

    address_terms = [str(value) for value in filters.get("address_terms") or []]
    if address_terms:
        conditions.append(
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

    uploader_names = [str(value).lower() for value in filters.get("uploader_names") or []]
    if uploader_names:
        conditions.append(func.lower(SourceDocument.slack_user_name).in_(uploader_names))

    markets = [str(value) for value in filters.get("markets") or []]
    if markets:
        conditions.append(or_(*[PropertyRecord.market.ilike(f"%{market}%") for market in markets]))

    locations = [str(value) for value in filters.get("locations") or []]
    if locations:
        location_conditions = []
        for location in locations:
            pattern = f"%{location}%"
            location_conditions.extend(
                [
                    PropertyRecord.country.ilike(pattern),
                    PropertyRecord.country_code.ilike(pattern),
                    PropertyRecord.region.ilike(pattern),
                    PropertyRecord.state_province.ilike(pattern),
                    PropertyRecord.county_district.ilike(pattern),
                    PropertyRecord.city.ilike(pattern),
                    PropertyRecord.locality.ilike(pattern),
                    PropertyRecord.neighborhood.ilike(pattern),
                    PropertyRecord.submarket.ilike(pattern),
                    PropertyRecord.postal_code.ilike(pattern),
                    PropertyRecord.market.ilike(pattern),
                ]
            )
        conditions.append(or_(*location_conditions))

    statuses = [str(value) for value in filters.get("statuses") or []]
    if statuses:
        status_conditions = []
        for status in statuses:
            pattern = f"%{status.replace('_', ' ')}%"
            status_conditions.extend(
                [
                    PropertyRecord.status.ilike(f"%{status}%"),
                    PropertyRecord.status.ilike(pattern),
                    PropertyRecord.availability.ilike(pattern),
                ]
            )
            if status == "available":
                status_conditions.extend(
                    [
                        PropertyRecord.availability.ilike("%immediate%"),
                        PropertyRecord.availability.ilike("%now%"),
                        PropertyRecord.availability.ilike("%vacant%"),
                    ]
                )
            if status == "coming_soon":
                status_conditions.extend(
                    [
                        PropertyRecord.availability.ilike("%soon%"),
                        PropertyRecord.availability.ilike("%q2%"),
                        PropertyRecord.availability.ilike("%q3%"),
                        PropertyRecord.availability.ilike("%june%"),
                        PropertyRecord.availability.ilike("%july%"),
                        PropertyRecord.availability.ilike("%august%"),
                    ]
                )
        conditions.append(or_(*status_conditions))

    usage_types = [str(value) for value in filters.get("usage_types") or []]
    if usage_types:
        usage_conditions = []
        for usage_type in usage_types:
            pattern = f"%{usage_type}%"
            usage_conditions.extend(
                [
                    PropertyRecord.usage_type.ilike(pattern),
                    PropertyRecord.asset_class.ilike(pattern),
                    PropertyRecord.property_subtype.ilike(pattern),
                    SourceDocument.raw_text.ilike(pattern),
                ]
            )
            if usage_type == "logistics":
                usage_conditions.extend(
                    [
                        PropertyRecord.property_type.ilike("%industrial%"),
                        PropertyRecord.property_subtype.ilike("%warehouse%"),
                        PropertyRecord.property_subtype.ilike("%distribution%"),
                    ]
                )
        conditions.append(or_(*usage_conditions))

    facing_terms = [str(value) for value in filters.get("facing") or []]
    if facing_terms:
        conditions.append(or_(*[PropertyRecord.facing.ilike(f"%{facing}%") for facing in facing_terms]))

    furnishing_statuses = [str(value) for value in filters.get("furnishing_statuses") or []]
    if furnishing_statuses:
        furnishing_conditions = []
        for furnishing_status in furnishing_statuses:
            furnishing_conditions.extend(
                [
                    PropertyRecord.furnishing_status.ilike(f"%{furnishing_status}%"),
                    PropertyRecord.furnishing_status.ilike(f"%{furnishing_status.replace('_', ' ')}%"),
                ]
            )
        conditions.append(or_(*furnishing_conditions))

    infrastructure_terms = [str(value) for value in filters.get("infrastructure_terms") or []]
    if infrastructure_terms:
        infrastructure_conditions = []
        for term in infrastructure_terms:
            pattern = f"%{term}%"
            infrastructure_conditions.extend(
                [
                    PropertyRecord.loading_access.ilike(pattern),
                    PropertyRecord.nearest_highway.ilike(pattern),
                    PropertyRecord.rail_access.ilike(pattern),
                    PropertyRecord.public_transit_notes.ilike(pattern),
                    PropertyRecord.additional_information.ilike(pattern),
                    PropertyRecord.amenities_json.cast(String).ilike(pattern),
                    PropertyRecord.infrastructure_json.cast(String).ilike(pattern),
                    PropertyRecord.tags_json.cast(String).ilike(pattern),
                ]
            )
        conditions.append(or_(*infrastructure_conditions))

    keywords = [] if filters.get("intent") == "tenant_fit" else [str(value) for value in filters.get("keywords") or []]
    if keywords:
        keyword_conditions = []
        for keyword in keywords:
            keyword_conditions.extend(
                [
                    Chunk.chunk_text.ilike(f"%{keyword}%"),
                    SourceDocument.raw_text.ilike(f"%{keyword}%"),
                    PropertyRecord.address.ilike(f"%{keyword}%"),
                    PropertyRecord.market.ilike(f"%{keyword}%"),
                    PropertyRecord.city.ilike(f"%{keyword}%"),
                    PropertyRecord.neighborhood.ilike(f"%{keyword}%"),
                    PropertyRecord.submarket.ilike(f"%{keyword}%"),
                    PropertyRecord.additional_information.ilike(f"%{keyword}%"),
                ]
            )
        conditions.append(or_(*keyword_conditions))

    price_lt = _as_decimal(filters.get("price_per_sq_ft_lt"))
    if price_lt is not None:
        conditions.append(and_(PropertyRecord.price_per_sq_ft.is_not(None), PropertyRecord.price_per_sq_ft < price_lt))

    price_gt = _as_decimal(filters.get("price_per_sq_ft_gt"))
    if price_gt is not None:
        conditions.append(and_(PropertyRecord.price_per_sq_ft.is_not(None), PropertyRecord.price_per_sq_ft > price_gt))

    sale_price_lt = _as_decimal(filters.get("sale_price_lt"))
    if sale_price_lt is not None:
        conditions.append(and_(PropertyRecord.sale_price.is_not(None), PropertyRecord.sale_price < sale_price_lt))

    sale_price_gt = _as_decimal(filters.get("sale_price_gt"))
    if sale_price_gt is not None:
        conditions.append(and_(PropertyRecord.sale_price.is_not(None), PropertyRecord.sale_price > sale_price_gt))

    cap_rate_gte = _as_decimal(filters.get("cap_rate_gte"))
    if cap_rate_gte is not None:
        conditions.append(and_(PropertyRecord.cap_rate.is_not(None), PropertyRecord.cap_rate >= cap_rate_gte))

    cap_rate_lte = _as_decimal(filters.get("cap_rate_lte"))
    if cap_rate_lte is not None:
        conditions.append(and_(PropertyRecord.cap_rate.is_not(None), PropertyRecord.cap_rate <= cap_rate_lte))

    if filters.get("sq_ft_gte") is not None:
        conditions.append(and_(PropertyRecord.sq_ft.is_not(None), PropertyRecord.sq_ft >= int(filters["sq_ft_gte"])))
    if filters.get("sq_ft_lte") is not None:
        conditions.append(and_(PropertyRecord.sq_ft.is_not(None), PropertyRecord.sq_ft <= int(filters["sq_ft_lte"])))

    clear_height_ft_gte = _as_decimal(filters.get("clear_height_ft_gte"))
    if clear_height_ft_gte is not None:
        conditions.append(and_(PropertyRecord.clear_height_ft.is_not(None), PropertyRecord.clear_height_ft >= clear_height_ft_gte))

    if filters.get("dock_doors_gte") is not None:
        conditions.append(and_(PropertyRecord.dock_doors.is_not(None), PropertyRecord.dock_doors >= int(filters["dock_doors_gte"])))
    if filters.get("trailer_parking_spaces_gte") is not None:
        conditions.append(and_(PropertyRecord.trailer_parking_spaces.is_not(None), PropertyRecord.trailer_parking_spaces >= int(filters["trailer_parking_spaces_gte"])))
    if filters.get("parking_spaces_gte") is not None:
        conditions.append(and_(PropertyRecord.parking_spaces.is_not(None), PropertyRecord.parking_spaces >= int(filters["parking_spaces_gte"])))

    availability_before = _parse_date(filters.get("availability_before"))
    if availability_before is not None:
        conditions.append(and_(PropertyRecord.availability_date.is_not(None), PropertyRecord.availability_date <= availability_before))
    if bool(filters.get("require_immediate")):
        conditions.append(
            or_(
                PropertyRecord.availability.ilike("%immediate%"),
                PropertyRecord.availability.ilike("%now%"),
                and_(PropertyRecord.availability_date.is_not(None), PropertyRecord.availability_date <= DEMO_REFERENCE_DATE),
            )
        )
    if bool(filters.get("requires_coordinates")):
        conditions.append(and_(PropertyRecord.geo_lat.is_not(None), PropertyRecord.geo_lng.is_not(None)))

    return conditions


def build_property_query(filters: dict[str, object]) -> Select[tuple[PropertyRecord, SourceDocument, Chunk | None]]:
    statement = (
        select(PropertyRecord, SourceDocument, Chunk)
        .join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
        .outerjoin(Chunk, PropertyRecord.chunk_id == Chunk.id)
    )
    conditions = _build_conditions(filters)
    if conditions:
        statement = statement.where(*conditions)
    return statement


def _dedupe_key(property_record: PropertyRecord) -> str:
    return property_record.duplicate_group_key or property_record.normalized_address or str(property_record.id)


def _priority_tuple(match: StructuredPropertyMatch) -> tuple[float, float, float, str]:
    authority = float(match.property_record.source_authority_score or Decimal("0"))
    freshness = float(match.property_record.freshness_score or Decimal("0"))
    posted = match.source_document.posted_at.timestamp() if match.source_document.posted_at is not None else 0.0
    return (authority, freshness, posted, match.property_record.address or "")


def _score(match_count: int, property_record: PropertyRecord) -> Decimal:
    authority = float(property_record.source_authority_score or Decimal("0"))
    freshness = float(property_record.freshness_score or Decimal("0"))
    confidence = float(property_record.confidence or Decimal("0"))
    raw_score = 0.38 + (0.07 * match_count) + (0.17 * authority) + (0.13 * freshness) + (0.08 * confidence)
    bounded = max(0.0500, min(0.9999, raw_score))
    return Decimal(f"{bounded:.4f}")


def _matched_fields(filters: dict[str, object], property_record: PropertyRecord, chunk: Chunk | None) -> list[str]:
    fields: list[str] = []
    if filters.get("property_types"):
        fields.append("property_type")
    if filters.get("address_terms"):
        fields.append("normalized_address")
    if filters.get("uploader_names"):
        fields.append("slack_user_name")
    if filters.get("markets"):
        fields.append("market")
    if filters.get("locations"):
        fields.append("location")
    if filters.get("statuses"):
        fields.append("status")
    if filters.get("usage_types"):
        fields.append("usage_type")
    if filters.get("facing"):
        fields.append("facing")
    if filters.get("furnishing_statuses"):
        fields.append("furnishing_status")
    if filters.get("infrastructure_terms"):
        fields.append("infrastructure")
    if filters.get("price_per_sq_ft_lt") is not None or filters.get("price_per_sq_ft_gt") is not None:
        fields.append("price_per_sq_ft")
    if filters.get("sale_price_lt") is not None or filters.get("sale_price_gt") is not None:
        fields.append("sale_price")
    if filters.get("cap_rate_gte") is not None or filters.get("cap_rate_lte") is not None:
        fields.append("cap_rate")
    if filters.get("sq_ft_gte") is not None or filters.get("sq_ft_lte") is not None:
        fields.append("sq_ft")
    if filters.get("clear_height_ft_gte") is not None:
        fields.append("clear_height_ft")
    if filters.get("dock_doors_gte") is not None:
        fields.append("dock_doors")
    if filters.get("trailer_parking_spaces_gte") is not None:
        fields.append("trailer_parking_spaces")
    if filters.get("parking_spaces_gte") is not None:
        fields.append("parking_spaces")
    if filters.get("availability_before") is not None or filters.get("require_immediate"):
        fields.append("availability")
    if filters.get("requires_coordinates"):
        fields.append("geo")

    chunk_text = chunk.chunk_text.lower() if chunk is not None else ""
    for keyword in [str(value) for value in filters.get("keywords") or []]:
        if keyword.lower() in chunk_text or keyword.lower() in (property_record.market or "").lower():
            fields.append(keyword)

    return sorted(set(fields)) or ["structured_match"]


def _selection_reason(matched_fields: list[str]) -> str:
    labels = ", ".join(matched_fields)
    return f"structured query matched: {labels}"


def _sort_matches(matches: list[StructuredPropertyMatch], sort_mode: str | None) -> list[StructuredPropertyMatch]:
    if sort_mode == "price_asc":
        return sorted(matches, key=lambda item: (item.property_record.price_per_sq_ft is None, item.property_record.price_per_sq_ft or Decimal("0"), item.property_record.address or ""))
    if sort_mode == "sale_price_asc":
        return sorted(matches, key=lambda item: (item.property_record.sale_price is None, item.property_record.sale_price or Decimal("0"), item.property_record.address or ""))
    if sort_mode == "cap_rate_desc":
        return sorted(matches, key=lambda item: (item.property_record.cap_rate or Decimal("0"), item.property_record.address or ""), reverse=True)
    if sort_mode == "size_desc":
        return sorted(matches, key=lambda item: (item.property_record.sq_ft or 0, item.property_record.address or ""), reverse=True)
    if sort_mode == "availability_asc":
        return sorted(matches, key=lambda item: (item.property_record.availability_date is None, item.property_record.availability_date or date.max, item.property_record.address or ""))
    return sorted(matches, key=_priority_tuple, reverse=True)


async def retrieve_structured_property_matches(
    session: AsyncSession,
    filters: dict[str, object],
    *,
    dedupe: bool = True,
) -> list[StructuredPropertyMatch]:
    rows = await session.execute(build_property_query(filters))
    matches: list[StructuredPropertyMatch] = []
    for property_record, source_document, chunk in rows:
        fields = _matched_fields(filters, property_record, chunk)
        matches.append(
            StructuredPropertyMatch(
                property_record=property_record,
                source_document=source_document,
                chunk=chunk,
                matched_fields=fields,
                relevance_score=_score(len(fields), property_record),
                selection_reason=_selection_reason(fields),
            )
        )

    if dedupe:
        deduped: dict[str, StructuredPropertyMatch] = {}
        for match in matches:
            key = _dedupe_key(match.property_record)
            existing = deduped.get(key)
            if existing is None or _priority_tuple(match) > _priority_tuple(existing):
                deduped[key] = match
        matches = list(deduped.values())

    sorted_matches = _sort_matches(matches, str(filters.get("sort") or "") or None)
    limit = int(filters.get("limit") or 5)
    return sorted_matches[:limit]


async def retrieve_relaxed_property_matches(
    session: AsyncSession,
    filters: dict[str, object],
    *,
    limit: int = 3,
) -> list[StructuredPropertyMatch]:
    relaxed = dict(filters)
    for key in (
        "price_per_sq_ft_lt",
        "price_per_sq_ft_gt",
        "sale_price_lt",
        "sale_price_gt",
        "cap_rate_gte",
        "cap_rate_lte",
        "sq_ft_gte",
        "sq_ft_lte",
        "clear_height_ft_gte",
        "dock_doors_gte",
        "trailer_parking_spaces_gte",
        "parking_spaces_gte",
        "availability_before",
        "require_immediate",
        "requires_coordinates",
        "keywords",
    ):
        relaxed[key] = None if key != "keywords" else []
    relaxed["limit"] = limit
    return await retrieve_structured_property_matches(session, relaxed)


async def retrieve_tenant_fit_matches(session: AsyncSession, filters: dict[str, object]) -> list[StructuredPropertyMatch]:
    search_filters = dict(filters)
    search_filters["keywords"] = []
    base_matches = await retrieve_structured_property_matches(session, search_filters, dedupe=True)

    tenant_terms = [str(value).lower() for value in filters.get("keywords") or []]
    ranked: list[tuple[tuple[float, float, float, float, str], StructuredPropertyMatch]] = []
    for match in base_matches:
        chunk_text = match.chunk.chunk_text.lower() if match.chunk is not None else ""
        term_hits = [term for term in tenant_terms if term in chunk_text or term in (match.property_record.market or "").lower()]
        price = float(match.property_record.price_per_sq_ft or Decimal("999"))
        sq_ft = float(match.property_record.sq_ft or 0)
        availability_bonus = 0.18 if match.property_record.availability_date and match.property_record.availability_date <= date(2026, 8, 31) else 0.0
        price_bonus = 0.20 if price <= 35 else 0.0
        size_bonus = 0.12 if sq_ft >= 15000 else 0.0
        term_bonus = 0.08 * len(term_hits)
        quality_bonus = float(match.relevance_score) * 0.35
        tenant_score = quality_bonus + availability_bonus + price_bonus + size_bonus + term_bonus
        fields = sorted(set([*match.matched_fields, *term_hits, "tenant_fit_score"]))
        availability_rank = -float(match.property_record.availability_date.toordinal()) if match.property_record.availability_date else -float(date.max.toordinal())
        ranked.append(
            (
                (tenant_score, -price, sq_ft, availability_rank, match.property_record.address or ""),
                StructuredPropertyMatch(
                    property_record=match.property_record,
                    source_document=match.source_document,
                    chunk=match.chunk,
                    matched_fields=fields,
                    relevance_score=Decimal(f"{min(0.9999, max(0.0500, tenant_score)):.4f}"),
                    selection_reason="local tenant-fit heuristic matched price, size, availability, and source quality",
                ),
            )
        )

    ranked.sort(key=lambda item: item[0], reverse=True)
    return [match for _, match in ranked[: int(filters.get("limit") or 5)]]


def _missing_fields_for_record(property_record: PropertyRecord, source_document: SourceDocument) -> list[str]:
    missing: list[str] = []
    if not property_record.address:
        missing.append("address")
    if not property_record.property_type or property_record.property_type == "unknown":
        missing.append("property_type")
    if property_record.sq_ft is None:
        missing.append("sq_ft")
    if property_record.price_per_sq_ft is None:
        missing.append("price_per_sq_ft")
    if not property_record.availability:
        missing.append("availability")
    if not property_record.market:
        missing.append("market")
    if property_record.geo_lat is None or property_record.geo_lng is None:
        missing.append("geo")
    if not property_record.status:
        missing.append("status")
    if not property_record.city:
        missing.append("city")
    if not property_record.locality:
        missing.append("locality")
    if not property_record.neighborhood:
        missing.append("neighborhood")
    if not property_record.map_url:
        missing.append("map_url")
    if not property_record.additional_information:
        missing.append("additional_information")
    if not source_document.source_url:
        missing.append("source_url")
    return missing


async def collect_data_quality_report(session: AsyncSession) -> dict[str, object]:
    source_rows = list((await session.execute(select(SourceDocument))).scalars())
    property_rows = list(
        (
            await session.execute(
                select(PropertyRecord, SourceDocument).join(SourceDocument, PropertyRecord.document_id == SourceDocument.id)
            )
        ).all()
    )
    chunk_doc_ids = set((await session.execute(select(Chunk.document_id))).scalars())
    property_doc_ids = {property_record.document_id for property_record, _ in property_rows}

    missing_counts = {field_name: 0 for field_name in CRITICAL_PROPERTY_FIELDS + ["source_url"]}
    records_with_missing: list[dict[str, object]] = []
    groups: dict[str, list[PropertyRecord]] = {}
    for property_record, source_document in property_rows:
        missing = _missing_fields_for_record(property_record, source_document)
        if missing:
            records_with_missing.append(
                {
                    "address": property_record.address,
                    "property_type": property_record.property_type,
                    "missing_fields": missing,
                }
            )
        for field_name in missing:
            missing_counts[field_name] = missing_counts.get(field_name, 0) + 1
        if property_record.duplicate_group_key:
            groups.setdefault(property_record.duplicate_group_key, []).append(property_record)

    conflict_groups: list[dict[str, object]] = []
    for group_key, records in groups.items():
        sq_ft_values = sorted({record.sq_ft for record in records if record.sq_ft is not None})
        price_values = sorted({str(record.price_per_sq_ft) for record in records if record.price_per_sq_ft is not None})
        if len(sq_ft_values) > 1 or len(price_values) > 1:
            conflict_groups.append(
                {
                    "duplicate_group_key": group_key,
                    "sq_ft_values": sq_ft_values,
                    "price_per_sq_ft_values": price_values,
                    "record_count": len(records),
                }
            )

    sources_without_chunks = [source for source in source_rows if source.id not in chunk_doc_ids]
    sources_without_properties = [source for source in source_rows if source.id not in property_doc_ids]

    return {
        "source_document_count": len(source_rows),
        "property_record_count": len(property_rows),
        "sources_without_chunks": [_source_label(source) for source in sources_without_chunks],
        "sources_without_properties": [_source_label(source) for source in sources_without_properties],
        "missing_field_counts": missing_counts,
        "records_with_missing_fields": records_with_missing,
        "conflict_groups": conflict_groups,
        "geospatial": await get_postgis_status(session),
        "toolhouse_readiness": {
            "status": "ready_for_bounded_agent" if not sources_without_chunks else "needs_ingestion_attention",
            "notes": [
                "Evidence IDs and source summaries are available for escalation.",
                "Sources without extracted property records should be treated as context, not structured facts.",
            ],
        },
    }


async def explain_no_results(session: AsyncSession, filters: dict[str, object]) -> dict[str, object]:
    relaxed_matches = await retrieve_relaxed_property_matches(session, filters)
    return {
        "applied_query_constructor": describe_query_constructor(filters),
        "blocking_filters": [condition for condition in describe_query_constructor(filters)["conditions"] if condition["op"] in {"<", ">", ">=", "<=", "immediate_or_now"}],
        "closest_matches_after_relaxing_numeric_filters": [
            {
                "address": match.property_record.address,
                "property_type": match.property_record.property_type,
                "sq_ft": match.property_record.sq_ft,
                "price_per_sq_ft": str(match.property_record.price_per_sq_ft) if match.property_record.price_per_sq_ft is not None else None,
                "availability": match.property_record.availability,
                "source": _source_label(match.source_document),
            }
            for match in relaxed_matches
        ],
    }


def _source_label(source_document: SourceDocument) -> str:
    if source_document.file_name:
        return source_document.file_name
    if source_document.source_type == "slack_message":
        return "Slack message"
    return source_document.source_type


__all__ = [
    "StructuredPropertyMatch",
    "build_property_query",
    "collect_data_quality_report",
    "describe_query_constructor",
    "explain_no_results",
    "retrieve_relaxed_property_matches",
    "retrieve_structured_property_matches",
    "retrieve_tenant_fit_matches",
]
