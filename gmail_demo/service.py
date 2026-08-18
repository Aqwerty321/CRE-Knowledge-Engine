from __future__ import annotations

import csv
import hashlib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from app.retrieval.lexical_retriever import BM25LexicalRetriever
from app.retrieval.retrieval_types import RetrievalDocument
from app.retrieval.text_utils import contains_phrase, dedupe_strings, normalize_text
from gmail_demo.models import (
    ConstraintCheck,
    FeatureState,
    ListingEvent,
    PropertyMatch,
    PropertyDeleteEvent,
    PropertyRow,
    RequirementEvent,
    TenantRequirement,
)


PROPERTIES_SHEET_COLUMNS = [
    "property_id",
    "property_name",
    "address",
    "city",
    "submarket",
    "property_type",
    "suite",
    "available_sf",
    "min_divisible_sf",
    "max_contiguous_sf",
    "use_types",
    "available_from",
    "rent_psf_year",
    "lease_type",
    "opex_psf_year",
    "office_sf",
    "clear_height_ft",
    "power_amps",
    "voltage",
    "hvac",
    "clean_room",
    "dock_doors",
    "parking_per_1000",
    "status",
    "brochure_url",
    "source_message_id",
    "source_subject",
    "updated_at",
    "notes",
]

PROCESSED_EMAIL_COLUMNS = [
    "gmail_message_id",
    "gmail_thread_id",
    "subject",
    "event_type",
    "processed_at",
    "status",
    "result_summary",
]

DEMO_DATA_DIR = Path(__file__).resolve().parents[1] / "gmail-demo-data"
DEMO_PRIMARY_EMAIL = "aaditya@toolhouse.ai"
DEMO_APPROVED_SENDER = "aadityasoni2020@gmail.com"
DEMO_SUBJECT_PREFIX = "[CRE-DEMO]"

_CRE_QUERY_ALIASES: dict[str, tuple[str, ...]] = {
    "lab": ("lab", "laboratory", "electronics lab"),
    "research and development": ("r&d", "r and d", "research and development", "research development"),
    "clean room": ("clean room", "cleanroom", "clean-room"),
    "full hvac": ("full hvac", "100% hvac", "climate controlled"),
    "flex": ("flex", "flex space", "flex office"),
    "industrial": ("industrial", "warehouse", "distribution"),
    "power": ("power", "amps", "amperage", "electrical capacity"),
    "dock doors": ("dock", "dock door", "dock doors", "loading dock"),
    "square feet": ("sf", "sq ft", "square feet", "square footage"),
    "triple net": ("nnn", "triple net"),
}

_USE_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "lab": ("lab", "laboratory", "electronics lab"),
    "r&d": ("r&d", "r and d", "research and development", "research development"),
    "flex": ("flex", "flex space", "flex office"),
    "office": ("office",),
    "industrial": ("industrial",),
    "warehouse": ("warehouse", "distribution"),
    "manufacturing": ("manufacturing", "advanced manufacturing"),
}


def _validation_failure(exc: ValidationError) -> dict[str, Any]:
    return {
        "ok": False,
        "errors": [
            {
                "field": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ],
    }


def _sheet_row(property_row: PropertyRow) -> dict[str, Any]:
    row = property_row.model_dump(mode="json")
    row["use_types"] = "; ".join(property_row.use_types)
    return {column: row.get(column) for column in PROPERTIES_SHEET_COLUMNS}


def describe_demo_contract() -> dict[str, Any]:
    return {
        "database": "Google Sheets only",
        "worksheets": {
            "Properties": PROPERTIES_SHEET_COLUMNS,
            "ProcessedEmails": PROCESSED_EMAIL_COLUMNS,
        },
        "event_types": [
            "listing_update",
            "property_delete",
            "property_query",
            "tenant_requirement",
            "ignore",
        ],
        "idempotency_key": "gmail_message_id",
        "listing_row_key": "property_id",
        "listing_identity_lookup": ["property_name", "suite"],
        "retrieval": {
            "mode": "bm25s_lexical_plus_structured_constraints",
            "uses_embeddings": False,
            "uses_reranker": False,
            "evidence_source": "Properties worksheet rows supplied to the MCP tool",
        },
        "rules": [
            "Ignore quoted history, signatures, disclaimers, unsubscribe text, and tracking content when extracting facts.",
            "Write one Properties row per physical suite or availability.",
            "Resolve a property_name + suite to one property_id, then upsert Sheets only by property_id.",
            "Delete only after property_id or property_name + suite resolves to exactly one current row.",
            "Never treat UNKNOWN as a match.",
            "Use returned evidence IDs and snippets for property facts; do not answer from agent memory.",
            "Send a reply only for a [CRE-DEMO] thread received from aadityasoni2020@gmail.com.",
            "The only authorized outbound recipient is aadityasoni2020@gmail.com.",
            "Record every handled Gmail message in ProcessedEmails.",
        ],
    }


def get_seed_properties() -> dict[str, Any]:
    """Return the deterministic 30-row demo seed for Toolhouse to write to Sheets."""

    seed_path = DEMO_DATA_DIR / "properties.csv"
    if not seed_path.is_file():
        return {
            "ok": False,
            "error": "seed_file_not_found",
            "detail": f"Missing demo seed at {seed_path}.",
        }

    with seed_path.open(newline="", encoding="utf-8") as handle:
        raw_rows = list(csv.DictReader(handle))

    try:
        rows = [_sheet_row(PropertyRow.model_validate(row)) for row in raw_rows]
    except ValidationError as exc:
        return _validation_failure(exc)

    return {
        "ok": True,
        "worksheet": "Properties",
        "columns": PROPERTIES_SHEET_COLUMNS,
        "row_count": len(rows),
        "rows": rows,
        "write_mode": "create_only_when_worksheet_has_zero_data_rows",
    }


def _property_identity_key(property_name: str, suite: str | None) -> tuple[str, str]:
    return (normalize_text(property_name), normalize_text(suite or ""))


def _stable_email_property_id(source_message_id: str, property_name: str, suite: str | None) -> str:
    material = "|".join((source_message_id, *_property_identity_key(property_name, suite)))
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16].upper()
    return f"EMAIL-{digest}"


def validate_listing_event(
    event: dict[str, Any],
    existing_properties: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        parsed = ListingEvent.model_validate(event)
        parsed_existing = [PropertyRow.model_validate(row) for row in (existing_properties or [])]
    except ValidationError as exc:
        return _validation_failure(exc)

    existing_by_identity: dict[tuple[str, str], list[PropertyRow]] = {}
    existing_by_id: dict[str, list[PropertyRow]] = {}
    for existing in parsed_existing:
        key = _property_identity_key(existing.property_name, existing.suite)
        existing_by_identity.setdefault(key, []).append(existing)
        if existing.property_id:
            existing_by_id.setdefault(existing.property_id, []).append(existing)

    normalized_properties: list[dict[str, Any]] = []
    sheet_rows: list[dict[str, Any]] = []
    incoming_ids: set[str] = set()
    incoming_identities: set[tuple[str, str]] = set()
    for property_row in parsed.properties:
        identity = _property_identity_key(property_row.property_name, property_row.suite)
        identity_matches = existing_by_identity.get(identity, [])
        id_matches = existing_by_id.get(property_row.property_id or "", [])
        if len(identity_matches) > 1:
            return {
                "ok": False,
                "error": "ambiguous_property_identity",
                "detail": (
                    f"Properties contains {len(identity_matches)} rows for "
                    f"{property_row.property_name!r} suite {property_row.suite!r}; repair the Sheet before writing."
                ),
                "matching_property_ids": [item.property_id for item in identity_matches],
            }
        if len(id_matches) > 1:
            return {
                "ok": False,
                "error": "ambiguous_property_id",
                "detail": f"Properties contains {len(id_matches)} rows with property_id {property_row.property_id!r}.",
            }

        if parsed.operation == "create" and (identity_matches or id_matches):
            return {
                "ok": False,
                "error": "property_already_exists",
                "detail": "Create refused because the property ID or property_name + suite already exists.",
                "matching_property_ids": list(
                    dict.fromkeys(item.property_id for item in [*identity_matches, *id_matches] if item.property_id)
                ),
            }
        if parsed.operation == "update" and not (identity_matches or id_matches):
            return {
                "ok": False,
                "error": "property_not_found",
                "detail": "Update requires one existing row resolved by property_id or property_name + suite.",
            }

        if property_row.property_id and identity_matches:
            existing_identity_id = identity_matches[0].property_id
            if existing_identity_id and existing_identity_id != property_row.property_id:
                return {
                    "ok": False,
                    "error": "property_identity_conflict",
                    "detail": (
                        f"The supplied identity belongs to {existing_identity_id!r}, not "
                        f"{property_row.property_id!r}."
                    ),
                }

        if not property_row.property_id:
            if len(identity_matches) > 1:
                return {
                    "ok": False,
                    "error": "ambiguous_property_identity",
                    "detail": (
                        f"Properties contains {len(identity_matches)} rows for "
                        f"{property_row.property_name!r} suite {property_row.suite!r}; repair the Sheet before updating."
                    ),
                    "matching_property_ids": [item.property_id for item in identity_matches],
                }
            if len(identity_matches) == 1 and identity_matches[0].property_id:
                property_row.property_id = identity_matches[0].property_id
            else:
                property_row.property_id = _stable_email_property_id(
                    parsed.source_message_id,
                    property_row.property_name,
                    property_row.suite,
                )
        if property_row.property_id in incoming_ids or identity in incoming_identities:
            return {
                "ok": False,
                "error": "duplicate_property_in_event",
                "detail": "One listing event cannot write the same property_id or property_name + suite twice.",
            }
        incoming_ids.add(property_row.property_id)
        incoming_identities.add(identity)
        property_row.source_message_id = parsed.source_message_id
        property_row.source_subject = parsed.source_subject
        if parsed.received_at:
            property_row.updated_at = parsed.received_at
        normalized_properties.append(property_row.model_dump(mode="json"))
        sheet_rows.append(_sheet_row(property_row))

    return {
        "ok": True,
        "event_type": parsed.event_type,
        "operation": parsed.operation,
        "source_message_id": parsed.source_message_id,
        "source_thread_id": parsed.source_thread_id,
        "properties": normalized_properties,
        "sheet_rows": sheet_rows,
        "row_lookup_key": ["property_name", "suite"],
        "sheet_headers": PROPERTIES_SHEET_COLUMNS,
        "sheet_key_column": "property_id",
        "write_rule": "Upsert each complete sheet_rows item using property_id only.",
    }


def validate_property_delete(
    event: dict[str, Any],
    existing_properties: list[dict[str, Any]],
) -> dict[str, Any]:
    """Resolve one explicit delete command to one stable Sheet row key."""

    try:
        parsed = PropertyDeleteEvent.model_validate(event)
        parsed_existing = [PropertyRow.model_validate(row) for row in existing_properties]
    except ValidationError as exc:
        return _validation_failure(exc)

    target = parsed.target
    id_matches = [row for row in parsed_existing if target.property_id and row.property_id == target.property_id]
    identity_matches = [
        row
        for row in parsed_existing
        if target.property_name
        and target.suite
        and _property_identity_key(row.property_name, row.suite)
        == _property_identity_key(target.property_name, target.suite)
    ]

    if len(id_matches) > 1 or len(identity_matches) > 1:
        candidates = id_matches or identity_matches
        return {
            "ok": False,
            "error": "ambiguous_property_delete",
            "detail": "Delete target resolves to multiple current Sheet rows.",
            "matching_property_ids": [row.property_id for row in candidates],
        }

    resolved = id_matches[0] if id_matches else identity_matches[0] if identity_matches else None
    if resolved is None:
        return {
            "ok": False,
            "error": "property_not_found",
            "detail": "Delete requires one current row resolved by property_id or property_name + suite.",
        }
    supplied_full_identity = bool(target.property_name and target.suite)
    if target.property_id and supplied_full_identity:
        if not id_matches or not identity_matches or id_matches[0].property_id != identity_matches[0].property_id:
            return {
                "ok": False,
                "error": "property_identity_conflict",
                "detail": "The supplied property_id and property_name + suite do not resolve to the same row.",
            }
    if not resolved.property_id:
        return {
            "ok": False,
            "error": "property_id_required",
            "detail": "The resolved row has no stable property_id and cannot be deleted safely.",
        }

    return {
        "ok": True,
        "event_type": parsed.event_type,
        "operation": parsed.operation,
        "source_message_id": parsed.source_message_id,
        "source_thread_id": parsed.source_thread_id,
        "worksheet": "Properties",
        "delete_key_column": "property_id",
        "delete_key_value": resolved.property_id,
        "matched_property": resolved.model_dump(mode="json"),
        "reason": parsed.reason,
        "write_rule": "Delete exactly one row whose property_id equals delete_key_value, then verify it is absent.",
    }


def validate_requirement_event(event: dict[str, Any]) -> dict[str, Any]:
    try:
        parsed = RequirementEvent.model_validate(event)
    except ValidationError as exc:
        return _validation_failure(exc)

    requirement = parsed.requirement
    if not requirement.source_message_id:
        requirement.source_message_id = parsed.source_message_id
    if not requirement.source_thread_id:
        requirement.source_thread_id = parsed.source_thread_id
    if not requirement.requester_email:
        requirement.requester_email = parsed.sender_email

    return {
        "ok": True,
        "event_type": parsed.event_type,
        "source_message_id": parsed.source_message_id,
        "source_thread_id": parsed.source_thread_id,
        "requirement": requirement.model_dump(mode="json"),
    }


def _check(name: str, status: str, detail: str) -> ConstraintCheck:
    return ConstraintCheck(name=name, status=status, detail=detail)  # type: ignore[arg-type]


def _normalized(value: str | None) -> str:
    return (value or "").strip().lower()


def _contains_any(values: list[str], candidates: list[str]) -> bool:
    normalized_values = {_normalized(value) for value in values}
    normalized_candidates = {_normalized(value) for value in candidates}
    return bool(normalized_values & normalized_candidates)


def _canonical_use_types(values: list[str]) -> set[str]:
    canonical: set[str] = set()
    for value in values:
        normalized = normalize_text(value)
        if not normalized:
            continue
        canonical.add(normalized)
        for concept, aliases in _USE_TYPE_ALIASES.items():
            if any(contains_phrase(normalized, alias) for alias in aliases):
                canonical.add(concept)
    return canonical


def _use_types_overlap(values: list[str], candidates: list[str]) -> bool:
    """Match explicit CRE use aliases without fuzzy or semantic inference."""

    return bool(_canonical_use_types(values) & _canonical_use_types(candidates))


def _expand_cre_query(query: str) -> tuple[str, ...]:
    normalized_query = normalize_text(query)
    expanded: list[str] = [normalized_query]
    for concept, aliases in _CRE_QUERY_ALIASES.items():
        if any(contains_phrase(normalized_query, alias) for alias in aliases):
            expanded.extend((concept, *aliases))
    return dedupe_strings(expanded)


def _property_retrieval_text(property_row: PropertyRow) -> str:
    parts = [
        property_row.property_name,
        property_row.property_name,
        f"suite {property_row.suite}" if property_row.suite else "",
        property_row.address or "",
        property_row.city or "",
        property_row.submarket or "",
        property_row.property_type or "",
        " ".join(property_row.use_types),
        " ".join(property_row.use_types),
        f"{property_row.available_sf} sf square feet",
        f"minimum divisible {property_row.min_divisible_sf} sf" if property_row.min_divisible_sf else "",
        f"maximum contiguous {property_row.max_contiguous_sf} sf" if property_row.max_contiguous_sf else "",
        f"power {property_row.power_amps} amps" if property_row.power_amps is not None else "",
        f"hvac {property_row.hvac.value}",
        f"clean room {property_row.clean_room.value}",
        f"rent {property_row.rent_psf_year} psf year" if property_row.rent_psf_year is not None else "",
        f"opex {property_row.opex_psf_year} psf year" if property_row.opex_psf_year is not None else "",
        property_row.lease_type or "",
        property_row.status,
        property_row.source_subject or "",
        property_row.notes or "",
    ]
    return " | ".join(part for part in parts if part)


def _property_evidence_id(property_row: PropertyRow, row_index: int) -> str:
    row_key = property_row.property_id or f"row-{row_index + 1}"
    return f"sheet:Properties:{row_key}"


def _property_evidence_snippet(property_row: PropertyRow) -> str:
    fields = [property_row.property_name]
    if property_row.suite:
        fields.append(f"Suite {property_row.suite}")
    if property_row.city:
        fields.append(property_row.city)
    if property_row.property_type:
        fields.append(property_row.property_type)
    fields.append(f"{property_row.available_sf:,} SF")
    if property_row.use_types:
        fields.append(f"uses: {', '.join(property_row.use_types)}")
    if property_row.power_amps is not None:
        fields.append(f"power: {property_row.power_amps:,}A")
    fields.extend((f"HVAC: {property_row.hvac.value}", f"clean room: {property_row.clean_room.value}"))
    if property_row.rent_psf_year is not None:
        fields.append(f"rent: ${property_row.rent_psf_year:,.2f}/SF/year")
    if property_row.opex_psf_year is not None:
        fields.append(f"OPEX: ${property_row.opex_psf_year:,.2f}/SF/year")
    fields.append(f"status: {property_row.status}")
    return " | ".join(fields)


def _property_evidence(
    property_row: PropertyRow,
    row_index: int,
    *,
    lexical_score: float = 0.0,
    matched_terms: tuple[str, ...] = (),
) -> dict[str, Any]:
    return {
        "evidence_id": _property_evidence_id(property_row, row_index),
        "lexical_score": round(lexical_score, 6),
        "matched_terms": list(matched_terms),
        "snippet": _property_evidence_snippet(property_row),
        "source": {
            "worksheet": "Properties",
            "property_id": property_row.property_id,
            "source_message_id": property_row.source_message_id,
            "source_subject": property_row.source_subject,
            "updated_at": property_row.updated_at,
        },
    }


def _retrieve_property_rows(
    query: str,
    properties: list[PropertyRow],
    *,
    limit: int,
) -> tuple[list[tuple[int, dict[str, Any]]], tuple[str, ...]]:
    expanded_terms = _expand_cre_query(query)
    if not expanded_terms or not properties:
        return [], expanded_terms

    documents = [
        RetrievalDocument(
            id=f"property-row-{index}",
            text=_property_retrieval_text(property_row),
            metadata={"row_index": index},
        )
        for index, property_row in enumerate(properties)
    ]
    retriever = BM25LexicalRetriever()
    hits = retriever.retrieve(
        " ".join(expanded_terms),
        documents,
        expanded_terms=expanded_terms,
        limit=max(1, min(limit, len(documents), 50)),
    )

    selected: list[tuple[int, dict[str, Any]]] = []
    for hit in hits:
        row_index = int(hit.document_id.rsplit("-", 1)[-1])
        selected.append(
            (
                row_index,
                _property_evidence(
                    properties[row_index],
                    row_index,
                    lexical_score=hit.score,
                    matched_terms=hit.matched_terms,
                ),
            )
        )
    return selected, expanded_terms


def _property_freshness_key(property_row: PropertyRow) -> tuple[str, str, str]:
    return (
        property_row.updated_at or "",
        property_row.source_message_id or "",
        property_row.property_id or "",
    )


def _deduplicate_property_rows(
    properties: list[PropertyRow],
) -> tuple[list[PropertyRow], list[dict[str, Any]]]:
    grouped: dict[tuple[str, str], list[PropertyRow]] = {}
    key_order: list[tuple[str, str]] = []
    for property_row in properties:
        key = _property_identity_key(property_row.property_name, property_row.suite)
        if key not in grouped:
            key_order.append(key)
        grouped.setdefault(key, []).append(property_row)

    selected: list[PropertyRow] = []
    duplicate_groups: list[dict[str, Any]] = []
    for key in key_order:
        rows = grouped[key]
        winner = max(rows, key=_property_freshness_key)
        selected.append(winner)
        if len(rows) > 1:
            duplicate_groups.append(
                {
                    "property_name": winner.property_name,
                    "suite": winner.suite,
                    "property_ids": [row.property_id for row in rows],
                    "selected_property_id": winner.property_id,
                    "selection_rule": "freshest updated_at, then source_message_id, then property_id",
                }
            )
    return selected, duplicate_groups


def search_property_knowledge(
    query: str,
    properties: list[dict[str, Any]],
    limit: int = 10,
) -> dict[str, Any]:
    """Return BM25-ranked property evidence from rows supplied by the connected Sheet."""

    if not query.strip():
        return {"ok": False, "error": "query_required", "detail": "Provide a non-empty retrieval query."}
    try:
        parsed_properties = [PropertyRow.model_validate(row) for row in properties]
    except ValidationError as exc:
        return _validation_failure(exc)

    deduplicated_properties, duplicate_groups = _deduplicate_property_rows(parsed_properties)

    selected, expanded_terms = _retrieve_property_rows(query, deduplicated_properties, limit=limit)
    results: list[dict[str, Any]] = []
    for row_index, evidence in selected:
        results.append(
            {
                "property": deduplicated_properties[row_index].model_dump(mode="json"),
                "evidence": evidence,
            }
        )

    return {
        "ok": True,
        "query": query,
        "retrieval_mode": "bm25s_lexical",
        "input_corpus_size": len(parsed_properties),
        "corpus_size": len(deduplicated_properties),
        "duplicate_groups": duplicate_groups,
        "result_count": len(results),
        "expanded_terms": list(expanded_terms),
        "uses_embeddings": False,
        "uses_reranker": False,
        "results": results,
        "rule": "Results are evidence from supplied Properties rows, not generated property facts.",
    }


def _feature_check(feature: str, property_row: PropertyRow) -> ConstraintCheck:
    normalized = _normalized(feature).replace("-", " ")
    if "clean" in normalized and "room" in normalized:
        if property_row.clean_room == FeatureState.YES:
            return _check("clean_room", "PASS", "Existing clean-room capability is confirmed.")
        if property_row.clean_room == FeatureState.NO:
            return _check("clean_room", "FAIL", "The row explicitly says no clean room.")
        return _check("clean_room", "UNKNOWN", "Clean-room capability is not confirmed.")
    if "hvac" in normalized:
        if property_row.hvac == FeatureState.YES:
            return _check("full_hvac", "PASS", "Full HVAC is confirmed.")
        if property_row.hvac == FeatureState.NO:
            return _check("full_hvac", "FAIL", "Full HVAC is explicitly unavailable.")
        return _check("full_hvac", "UNKNOWN", "HVAC coverage is not confirmed.")
    if "lab" in normalized:
        if any("lab" in use_type or "r&d" in use_type for use_type in property_row.use_types):
            return _check("lab_use", "PASS", "Lab/R&D use appears in the property row.")
        if property_row.use_types:
            return _check("lab_use", "FAIL", "The listed uses do not include lab/R&D.")
        return _check("lab_use", "UNKNOWN", "Permitted/current uses are missing.")
    if "dock" in normalized:
        if property_row.dock_doors is None:
            return _check("dock_doors", "UNKNOWN", "Dock-door count is missing.")
        if property_row.dock_doors > 0:
            return _check("dock_doors", "PASS", f"{property_row.dock_doors} dock door(s) listed.")
        return _check("dock_doors", "FAIL", "No dock doors are listed.")

    searchable = " ".join([property_row.notes or "", *property_row.use_types]).lower()
    if normalized and normalized in searchable:
        return _check(normalized.replace(" ", "_"), "PASS", f"'{feature}' appears in the property data.")
    return _check(normalized.replace(" ", "_") or "feature", "UNKNOWN", f"'{feature}' is not confirmed.")


def _feature_key(feature: str) -> str:
    normalized = normalize_text(feature)
    if "clean" in normalized and "room" in normalized:
        return "clean_room"
    if "hvac" in normalized:
        return "full_hvac"
    if "lab" in normalized:
        return "lab_use"
    if "dock" in normalized:
        return "dock_doors"
    return normalized.replace(" ", "_") or "feature"


def _match_one(requirement: TenantRequirement, property_row: PropertyRow) -> PropertyMatch:
    checks: list[ConstraintCheck] = []
    compatible_size_min_sf: int | None = None
    compatible_size_max_sf: int | None = None

    status = _normalized(property_row.status)
    if status in {"available", "active", "vacant", "future"}:
        checks.append(_check("availability", "PASS", f"Status is {property_row.status}."))
    elif status:
        checks.append(_check("availability", "FAIL", f"Status is {property_row.status}."))
    else:
        checks.append(_check("availability", "UNKNOWN", "Availability status is missing."))

    minimum = property_row.min_divisible_sf or property_row.available_sf
    maximum = property_row.max_contiguous_sf or property_row.available_sf
    if maximum < requirement.size_min_sf:
        checks.append(_check("size", "FAIL", f"Maximum contiguous area {maximum:,} SF is below {requirement.size_min_sf:,} SF."))
    elif minimum > requirement.size_max_sf:
        checks.append(_check("size", "FAIL", f"Minimum divisible area {minimum:,} SF exceeds {requirement.size_max_sf:,} SF."))
    else:
        compatible_size_min_sf = max(minimum, requirement.size_min_sf)
        compatible_size_max_sf = min(maximum, requirement.size_max_sf)
        checks.append(_check("size", "PASS", f"Divisible range {minimum:,}–{maximum:,} SF overlaps the requirement."))

    if requirement.city:
        if not property_row.city:
            checks.append(_check("city", "UNKNOWN", "Property city is missing."))
        elif _normalized(requirement.city) == _normalized(property_row.city):
            checks.append(_check("city", "PASS", f"Property is in {property_row.city}."))
        else:
            checks.append(_check("city", "FAIL", f"Property is in {property_row.city}, not {requirement.city}."))

    if requirement.submarkets:
        if not property_row.submarket:
            checks.append(_check("submarket", "UNKNOWN", "Submarket is missing."))
        elif _contains_any([property_row.submarket], requirement.submarkets):
            checks.append(_check("submarket", "PASS", f"Submarket {property_row.submarket} is requested."))
        else:
            checks.append(_check("submarket", "FAIL", f"Submarket {property_row.submarket} is outside the requested list."))

    if requirement.property_types:
        if not property_row.property_type:
            checks.append(_check("property_type", "UNKNOWN", "Property type is missing."))
        elif _contains_any([property_row.property_type], requirement.property_types):
            checks.append(_check("property_type", "PASS", f"Property type {property_row.property_type} is allowed."))
        else:
            checks.append(_check("property_type", "FAIL", f"Property type {property_row.property_type} is not requested."))

    if requirement.use_types:
        if not property_row.use_types:
            checks.append(_check("use_type", "UNKNOWN", "Use types are missing."))
        elif _use_types_overlap(property_row.use_types, requirement.use_types):
            checks.append(_check("use_type", "PASS", "At least one requested CRE use type matches."))
        else:
            checks.append(_check("use_type", "FAIL", "No requested use type matches the property row."))

    if requirement.min_power_amps is not None:
        if property_row.power_amps is None:
            checks.append(_check("power", "UNKNOWN", "Power capacity is missing."))
        elif property_row.power_amps >= requirement.min_power_amps:
            checks.append(_check("power", "PASS", f"{property_row.power_amps:,}A meets the {requirement.min_power_amps:,}A minimum."))
        else:
            checks.append(_check("power", "FAIL", f"{property_row.power_amps:,}A is below the {requirement.min_power_amps:,}A minimum."))

    required_features = list(requirement.required_features)
    if requirement.needs_clean_room:
        required_features.append("clean room")
    if requirement.needs_full_hvac:
        required_features.append("full hvac")
    seen_feature_keys: set[str] = set()
    for feature in required_features:
        key = _feature_key(feature)
        if key in seen_feature_keys:
            continue
        seen_feature_keys.add(key)
        checks.append(_feature_check(feature, property_row))

    failures = [check for check in checks if check.status == "FAIL"]
    unknowns = [check for check in checks if check.status == "UNKNOWN"]
    if failures:
        match_status = "NO_FIT"
    elif unknowns:
        match_status = "UNKNOWN"
    else:
        match_status = "FIT"

    score = max(0, min(100, 100 - (40 * len(failures)) - (10 * len(unknowns))))
    caveats = list(dict.fromkeys(check.detail for check in unknowns))
    return PropertyMatch(
        property=property_row,
        match_status=match_status,  # type: ignore[arg-type]
        score=score,
        compatible_size_min_sf=compatible_size_min_sf,
        compatible_size_max_sf=compatible_size_max_sf,
        checks=checks,
        caveats=caveats,
    )


def _requirement_retrieval_query(requirement: TenantRequirement) -> str:
    terms = [
        *requirement.use_types,
        *requirement.property_types,
        requirement.city or "",
        *requirement.submarkets,
        *requirement.required_features,
        *requirement.preferred_features,
        f"{requirement.size_min_sf} to {requirement.size_max_sf} sf",
        f"{requirement.min_power_amps} amps" if requirement.min_power_amps is not None else "",
        "clean room" if requirement.needs_clean_room else "",
        "full hvac" if requirement.needs_full_hvac else "",
        requirement.notes or "",
    ]
    return " ".join(term for term in terms if term)


def match_requirement(
    requirement: dict[str, Any],
    properties: list[dict[str, Any]],
    limit: int = 5,
    query: str = "",
) -> dict[str, Any]:
    try:
        parsed_requirement = TenantRequirement.model_validate(requirement)
        parsed_properties = [PropertyRow.model_validate(row) for row in properties]
    except ValidationError as exc:
        return _validation_failure(exc)

    deduplicated_properties, duplicate_groups = _deduplicate_property_rows(parsed_properties)

    retrieval_query = query.strip() or _requirement_retrieval_query(parsed_requirement)
    lexical_hits, expanded_terms = _retrieve_property_rows(
        retrieval_query,
        deduplicated_properties,
        limit=len(deduplicated_properties),
    )
    lexical_by_index = {row_index: evidence for row_index, evidence in lexical_hits}

    matches = [
        (index, _match_one(parsed_requirement, property_row))
        for index, property_row in enumerate(deduplicated_properties)
    ]
    rank = {"FIT": 0, "UNKNOWN": 1, "NO_FIT": 2}
    matches.sort(
        key=lambda indexed_item: (
            rank[indexed_item[1].match_status],
            -indexed_item[1].score,
            -lexical_by_index.get(indexed_item[0], {}).get("lexical_score", 0.0),
            indexed_item[1].property.property_name,
            indexed_item[1].property.suite or "",
        )
    )
    bounded_limit = max(1, min(limit, 20))
    selected = matches[:bounded_limit]

    selected_payloads: list[dict[str, Any]] = []
    for row_index, item in selected:
        payload = item.model_dump(mode="json")
        evidence = lexical_by_index.get(row_index) or _property_evidence(item.property, row_index)
        payload["retrieval_score"] = evidence["lexical_score"]
        payload["matched_terms"] = evidence["matched_terms"]
        payload["evidence"] = evidence
        selected_payloads.append(payload)

    return {
        "ok": True,
        "requirement": parsed_requirement.model_dump(mode="json"),
        "counts": {
            "FIT": sum(item.match_status == "FIT" for _, item in matches),
            "UNKNOWN": sum(item.match_status == "UNKNOWN" for _, item in matches),
            "NO_FIT": sum(item.match_status == "NO_FIT" for _, item in matches),
        },
        "retrieval": {
            "mode": "bm25s_lexical_plus_structured_constraints",
            "query": retrieval_query,
            "expanded_terms": list(expanded_terms),
            "input_corpus_size": len(parsed_properties),
            "corpus_size": len(deduplicated_properties),
            "duplicate_groups": duplicate_groups,
            "uses_embeddings": False,
            "uses_reranker": False,
        },
        "matches": selected_payloads,
        "rule": "UNKNOWN is never promoted to FIT.",
    }


def _format_money(value: float | None) -> str | None:
    return None if value is None else f"${value:,.2f}/SF/year"


def _format_match_size(item: PropertyMatch) -> str:
    row = item.property
    minimum = item.compatible_size_min_sf
    maximum = item.compatible_size_max_sf
    if minimum is None or maximum is None or minimum <= row.available_sf <= maximum:
        return f"{row.available_sf:,} SF"
    if minimum == maximum:
        compatible = f"{minimum:,} SF"
    else:
        compatible = f"{minimum:,}–{maximum:,} SF"
    return f"{compatible} divisible configuration within the {row.available_sf:,} SF suite"


def compose_requirement_reply(
    requirement: dict[str, Any],
    matches: list[dict[str, Any]],
    sender_name: str = "",
) -> dict[str, Any]:
    try:
        parsed_requirement = TenantRequirement.model_validate(requirement)
        parsed_matches = [PropertyMatch.model_validate(item) for item in matches]
    except ValidationError as exc:
        return _validation_failure(exc)

    source_subject = parsed_requirement.source_subject.strip()
    recipient = _normalized(parsed_requirement.requester_email)
    if recipient != DEMO_APPROVED_SENDER or not source_subject.upper().startswith(DEMO_SUBJECT_PREFIX):
        return {
            "ok": False,
            "error": "outbound_send_not_authorized",
            "detail": (
                f"Automatic sending is restricted to {DEMO_APPROVED_SENDER} "
                f"for subjects beginning with {DEMO_SUBJECT_PREFIX}."
            ),
            "requires_human_review": False,
            "send_automatically": False,
        }
    if not parsed_requirement.source_thread_id:
        return {
            "ok": False,
            "error": "source_thread_id_required",
            "detail": "A Gmail thread ID is required for the automatic reply.",
            "requires_human_review": False,
            "send_automatically": False,
        }

    usable = [item for item in parsed_matches if item.match_status in {"FIT", "UNKNOWN"}]
    greeting = parsed_requirement.requester_name or "there"
    lines = [f"Hi {greeting},", ""]

    if usable:
        lines.append("Thanks for reaching out. Based on the requirement, these are the closest options in our current sheet:")
        lines.append("")
        for item in usable:
            row = item.property
            label = row.property_name + (f" — Suite {row.suite}" if row.suite else "")
            summary = f"{label}: {_format_match_size(item)}"
            rate = _format_money(row.rent_psf_year)
            if rate:
                summary += f", {rate} {row.lease_type or ''}".rstrip()
            summary += f" [{item.match_status}]"
            lines.append(f"• {summary}")
            if item.caveats:
                lines.append(f"  Confirm: {'; '.join(item.caveats)}")
            if row.brochure_url:
                lines.append(f"  Brochure: {row.brochure_url}")
        lines.extend(["", "Let me know which options you would like to discuss or tour."])
    else:
        lines.extend(
            [
                "Thanks for reaching out. I do not yet have a confirmed match in the current property sheet.",
                "",
                "If any requirement can flex, send me the priorities and I will re-run the search.",
            ]
        )

    if sender_name:
        lines.extend(["", f"Best,\n{sender_name}"])

    subject = source_subject if source_subject.lower().startswith("re:") else f"Re: {source_subject}"
    return {
        "ok": True,
        "action": "send_reply",
        "from_account": DEMO_PRIMARY_EMAIL,
        "to": parsed_requirement.requester_email,
        "thread_id": parsed_requirement.source_thread_id,
        "subject": subject,
        "body_text": "\n".join(lines),
        "included_match_count": len(usable),
        "requires_human_review": False,
        "send_automatically": True,
        "authorization_scope": {
            "approved_sender": DEMO_APPROVED_SENDER,
            "required_subject_prefix": DEMO_SUBJECT_PREFIX,
            "reply_in_source_thread_only": True,
        },
    }


def compose_property_query_reply(
    query: str,
    source_message_id: str,
    source_thread_id: str,
    source_subject: str,
    requester_email: str,
    results: list[dict[str, Any]],
    sender_name: str = "",
    exact_property_name: str = "",
    exact_suite: str = "",
) -> dict[str, Any]:
    """Render a grounded reply from exact Sheet-search results for one ad hoc question."""

    if not query.strip():
        return {"ok": False, "error": "query_required", "send_automatically": False}
    recipient = _normalized(requester_email)
    if recipient != DEMO_APPROVED_SENDER or not source_subject.upper().startswith(DEMO_SUBJECT_PREFIX):
        return {
            "ok": False,
            "error": "outbound_send_not_authorized",
            "detail": (
                f"Automatic sending is restricted to {DEMO_APPROVED_SENDER} "
                f"for subjects beginning with {DEMO_SUBJECT_PREFIX}."
            ),
            "send_automatically": False,
        }
    if not source_message_id or not source_thread_id:
        return {
            "ok": False,
            "error": "source_message_and_thread_required",
            "send_automatically": False,
        }

    verified: list[tuple[PropertyRow, str]] = []
    try:
        for result in results[:10]:
            row = PropertyRow.model_validate(result.get("property"))
            evidence = result.get("evidence")
            evidence_id = evidence.get("evidence_id") if isinstance(evidence, dict) else None
            expected_evidence_id = f"sheet:Properties:{row.property_id}"
            if not row.property_id or evidence_id != expected_evidence_id:
                return {
                    "ok": False,
                    "error": "invalid_property_evidence",
                    "detail": "Every property query result must carry its exact Sheet evidence ID.",
                    "send_automatically": False,
                }
            verified.append((row, evidence_id))
    except ValidationError as exc:
        failure = _validation_failure(exc)
        failure["send_automatically"] = False
        return failure

    if exact_property_name.strip():
        requested_name = normalize_text(exact_property_name)
        requested_suite = normalize_text(exact_suite)
        verified = [
            item
            for item in verified
            if normalize_text(item[0].property_name) == requested_name
            and (not requested_suite or normalize_text(item[0].suite or "") == requested_suite)
        ]
    else:
        suite_results = [
            item
            for item in verified
            if item[0].suite and contains_phrase(query, item[0].suite)
        ]
        named_results = [item for item in verified if contains_phrase(query, item[0].property_name)]
        if named_results:
            named_suite_results = [
                item
                for item in named_results
                if item[0].suite and contains_phrase(query, item[0].suite)
            ]
            verified = named_suite_results or named_results
        elif len(suite_results) == 1:
            verified = suite_results

    lines = ["Hi,", "", "The current property sheet shows:", ""]
    if not verified:
        if exact_property_name.strip():
            identity = exact_property_name.strip()
            if exact_suite.strip():
                identity += f" — Suite {exact_suite.strip()}"
            lines.append(f"I did not find a supported result for {identity} in the current property sheet.")
        else:
            lines.append("I did not find a supported property result in the current sheet.")
    else:
        for row, _ in verified:
            label = row.property_name + (f" — Suite {row.suite}" if row.suite else "")
            fields = [f"{row.available_sf:,} SF", f"status: {row.status}"]
            if row.min_divisible_sf is not None:
                fields.append(f"minimum divisible: {row.min_divisible_sf:,} SF")
            if row.max_contiguous_sf is not None:
                fields.append(f"maximum contiguous: {row.max_contiguous_sf:,} SF")
            if row.rent_psf_year is not None:
                fields.append(f"rent: {_format_money(row.rent_psf_year)} {row.lease_type or ''}".rstrip())
            if row.opex_psf_year is not None:
                fields.append(f"OPEX: {_format_money(row.opex_psf_year)}")
            if row.office_sf is not None:
                fields.append(f"office: {row.office_sf:,} SF")
            if row.clear_height_ft is not None:
                fields.append(f"clear height: {row.clear_height_ft:g} ft")
            if row.power_amps is not None:
                voltage = f" at {row.voltage}" if row.voltage else ""
                fields.append(f"power: {row.power_amps:,}A{voltage}")
            fields.extend((f"HVAC: {row.hvac.value}", f"clean room: {row.clean_room.value}"))
            if row.dock_doors is not None:
                fields.append(f"dock doors: {row.dock_doors}")
            if row.parking_per_1000 is not None:
                fields.append(f"parking: {row.parking_per_1000:g}/1,000 SF")
            if row.available_from:
                fields.append(f"available from: {row.available_from}")
            lines.append(f"• {label}: {'; '.join(fields)}")
    if sender_name:
        lines.extend(["", f"Best,\n{sender_name}"])

    subject = source_subject if source_subject.lower().startswith("re:") else f"Re: {source_subject}"
    return {
        "ok": True,
        "action": "send_reply",
        "from_account": DEMO_PRIMARY_EMAIL,
        "to": requester_email,
        "thread_id": source_thread_id,
        "subject": subject,
        "body_text": "\n".join(lines),
        "evidence_ids": [evidence_id for _, evidence_id in verified],
        "included_result_count": len(verified),
        "exact_identity_scope": {
            "property_name": exact_property_name.strip() or None,
            "suite": exact_suite.strip() or None,
        },
        "requires_human_review": False,
        "send_automatically": True,
    }
