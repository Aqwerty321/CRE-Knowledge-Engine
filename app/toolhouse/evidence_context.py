from __future__ import annotations

import json
from collections import Counter, defaultdict
from typing import Any


BACKEND_MCP_TOOL_GUIDE: list[dict[str, object]] = [
    {
        "name": "explain_evidence",
        "use_when": "Start every deeper review by reading the stored query package, allowed evidence IDs, and decision summary.",
        "citation_scope": "Returns backend-minted evidence IDs that can be cited in final answers.",
    },
    {
        "name": "expand_query_context",
        "use_when": "Pull richer source details and aggregate summaries for an existing query bundle.",
        "citation_scope": "Context only unless it references evidence IDs already allowed for the query.",
    },
    {
        "name": "expand_query_evidence",
        "use_when": "Ask the backend to add more structured property evidence to the same query before citing it.",
        "citation_scope": "Mints additional backend evidence IDs for this query and expands the allowed citation set.",
    },
    {
        "name": "summarize_inventory",
        "use_when": "Get a one-call inventory snapshot by property type and market, plus cheapest, largest, and soonest-available ranked slices.",
        "citation_scope": "Read-only unless query_id is provided; ranked slices then mint query-scoped evidence IDs.",
    },
    {
        "name": "rank_properties",
        "use_when": "Rank structured results for objectives such as balanced review, cheapest, largest, soonest availability, or logistics tenant fit.",
        "citation_scope": "Read-only unless query_id is provided; then returned evidence_id values are backend-minted for the current query.",
    },
    {
        "name": "get_property_timeline",
        "use_when": "Trace one property/address/duplicate group across source documents to inspect freshness, conflicts, and provenance history.",
        "citation_scope": "Read-only unless query_id is provided; then timeline rows include query-scoped evidence IDs where available.",
    },
    {
        "name": "find_property_conflicts",
        "use_when": "Find duplicate property groups with conflicting size, rent, or availability values before making a confidence-sensitive answer.",
        "citation_scope": "Read-only unless query_id is provided; then conflict rows can expand query evidence for cited follow-up claims.",
    },
    {
        "name": "describe_backend_schema",
        "use_when": "Inspect supported filters, sort modes, aggregation metrics, and safe query examples before constructing tool calls.",
        "citation_scope": "Schema guidance only; does not provide factual CRE evidence.",
    },
    {
        "name": "search_properties",
        "use_when": "Run structured searches over normalized property records by type, market, address, price, size, timing, uploader, and keywords.",
        "citation_scope": "Read-only search result; use expand_query_evidence if the result must be cited in the final answer.",
    },
    {
        "name": "aggregate_properties",
        "use_when": "Compute counts, square-footage totals, rent averages, and ranges over backend records.",
        "citation_scope": "Aggregate context; cite the underlying query evidence or expanded evidence IDs for factual claims.",
    },
    {
        "name": "search_source_chunks",
        "use_when": "Search source chunks, raw text, and file names for operational wording, conflicts, amenities, and noisy terms.",
        "citation_scope": "Read-only search result; use explain_evidence or expand_query_evidence for final citation IDs.",
    },
    {
        "name": "get_source_detail",
        "use_when": "Inspect one source document's chunks and property records after a source ID is known.",
        "citation_scope": "Source context; cite allowed evidence IDs tied to the same source where possible.",
    },
    {
        "name": "nearby_properties",
        "use_when": "Run backend distance calculations from coordinates or a known property address.",
        "citation_scope": "Read-only proximity result; use expand_query_evidence if new results need final citations.",
    },
    {
        "name": "audit_data",
        "use_when": "Check corpus completeness, missing fields, and conflict groups before making a coverage-sensitive claim.",
        "citation_scope": "Audit context; does not mint claim-level evidence IDs.",
    },
]


def _property_record(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("property_record")
    return value if isinstance(value, dict) else {}


def _source_document(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("source_document")
    return value if isinstance(value, dict) else {}


def _chunk(item: dict[str, Any]) -> dict[str, Any]:
    value = item.get("chunk")
    return value if isinstance(value, dict) else {}


def _counter_payload(values: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(value for value in values if value).items()))


def _evidence_bytes(evidence: list[dict[str, Any]]) -> int:
    return len(json.dumps(evidence, default=str))


def _compact_evidence_item(item: dict[str, Any]) -> dict[str, object]:
    property_record = _property_record(item)
    source_document = _source_document(item)
    chunk = _chunk(item)
    return {
        "evidence_id": item.get("evidence_id"),
        "role": item.get("evidence_role") or "result",
        "selection_reason": item.get("selection_reason"),
        "relevance_score": item.get("relevance_score"),
        "matched_fields": list(item.get("matched_fields") or []),
        "property": {
            "id": property_record.get("id"),
            "address": property_record.get("address"),
            "property_type": property_record.get("property_type"),
            "sq_ft": property_record.get("sq_ft"),
            "price_per_sq_ft": property_record.get("price_per_sq_ft"),
            "availability": property_record.get("availability"),
            "availability_date": property_record.get("availability_date"),
            "market": property_record.get("market"),
            "duplicate_group_key": property_record.get("duplicate_group_key"),
        },
        "source": {
            "id": source_document.get("id"),
            "type": source_document.get("source_type"),
            "file_name": source_document.get("file_name"),
            "slack_user_name": source_document.get("slack_user_name"),
            "slack_channel_name": source_document.get("slack_channel_name"),
            "posted_at": source_document.get("posted_at"),
        },
        "chunk": {
            "id": chunk.get("id"),
            "page_number": chunk.get("page_number"),
            "row_number": chunk.get("row_number"),
            "section_name": chunk.get("section_name"),
            "text_preview": chunk.get("text_preview"),
        },
    }


def _source_manifest(evidence: list[dict[str, Any]]) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    evidence_ids_by_source: dict[str, list[str]] = defaultdict(list)
    addresses_by_source: dict[str, list[str]] = defaultdict(list)
    for item in evidence:
        source_document = _source_document(item)
        source_id = str(source_document.get("id") or "unknown")
        grouped.setdefault(
            source_id,
            {
                "source_document_id": source_document.get("id"),
                "source_type": source_document.get("source_type"),
                "file_name": source_document.get("file_name"),
                "source_url": source_document.get("source_url"),
                "slack_user_name": source_document.get("slack_user_name"),
                "slack_channel_name": source_document.get("slack_channel_name"),
                "posted_at": source_document.get("posted_at"),
            },
        )
        if item.get("evidence_id"):
            evidence_ids_by_source[source_id].append(str(item["evidence_id"]))
        address = _property_record(item).get("address")
        if address:
            addresses_by_source[source_id].append(str(address))

    manifest: list[dict[str, object]] = []
    for source_id, payload in grouped.items():
        manifest.append(
            {
                **payload,
                "evidence_ids": evidence_ids_by_source[source_id],
                "addresses": sorted(set(addresses_by_source[source_id])),
            }
        )
    return sorted(manifest, key=lambda item: str(item.get("file_name") or item.get("source_document_id") or ""))


def _recommended_mcp_calls(explain_payload: dict[str, Any]) -> list[dict[str, object]]:
    reason_codes = {str(value) for value in explain_payload.get("reason_codes") or []}
    snapshot = explain_payload.get("answer_snapshot") if isinstance(explain_payload.get("answer_snapshot"), dict) else {}
    filters = snapshot.get("filters") if isinstance(snapshot.get("filters"), dict) else {}
    query_constructor = filters.get("query_constructor") if isinstance(filters.get("query_constructor"), dict) else None
    calls: list[dict[str, object]] = [
        {
            "tool": "explain_evidence",
            "why": "Load the canonical evidence IDs, local answer, filters, and decision summary before writing a deeper answer.",
            "arguments": {"query_id": explain_payload.get("query_id")},
        },
        {
            "tool": "describe_backend_schema",
            "why": "Use this if constructing a fresh structured search or aggregate call.",
            "arguments": {},
        },
    ]
    if query_constructor is not None:
        calls.append(
            {
                "tool": "expand_query_context",
                "why": "Pull source details and aggregate summaries for the current backend-selected bundle.",
                "arguments": {"query_id": explain_payload.get("query_id"), "include_source_details": True, "max_sources": 8},
            }
        )
        calls.append(
            {
                "tool": "aggregate_properties",
                "why": "Check count, square-footage, and rent summaries over the same structured filters.",
                "arguments": {
                    "filters": filters,
                    "group_by": "property_type",
                    "metrics": ["count", "sum_sq_ft", "avg_price_per_sq_ft", "min_price_per_sq_ft", "max_price_per_sq_ft"],
                },
            }
        )
    if "broad_inventory" in reason_codes:
        calls.append(
            {
                "tool": "summarize_inventory",
                "why": "Use the backend coordinator to review all inventory slices and mint cited ranked evidence for broad inventory questions.",
                "arguments": {"query_id": explain_payload.get("query_id"), "filters": {"limit": 25}},
            }
        )
    if "hybrid_local_retrieval" in reason_codes or "subjective_intent" in reason_codes:
        calls.append(
            {
                "tool": "rank_properties",
                "why": "Rank candidate properties with backend-owned scoring before writing a subjective comparison.",
                "arguments": {"query_id": explain_payload.get("query_id"), "filters": filters or {"limit": 10}, "objective": "tenant fit", "keywords": []},
            }
        )
        calls.append(
            {
                "tool": "search_source_chunks",
                "why": "Find extra operational language or tenant-fit support in source chunks, then expand evidence if the result should be cited.",
                "arguments": {"query": explain_payload.get("query_text"), "filters": {"limit": 10}},
            }
        )
    return calls


def build_evidence_context(
    explain_payload: dict[str, Any],
    *,
    allowed_evidence_ids: list[str] | None = None,
) -> dict[str, object]:
    evidence = [dict(item) for item in list(explain_payload.get("evidence") or []) if isinstance(item, dict)]
    allowed_ids = allowed_evidence_ids or [str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")]
    property_records = [_property_record(item) for item in evidence]
    source_documents = [_source_document(item) for item in evidence]
    return {
        "policy_version": "evidence-context-v2",
        "scope": "The initial bundle contains backend-selected evidence for this query. Toolhouse may use read-only MCP tools for context and expand_query_evidence for more backend-minted citation IDs.",
        "citation_rule": "Final answered CRE claims must cite evidence IDs in allowed_evidence_ids. If a useful MCP result has no allowed ID, call expand_query_evidence or mark the claim as needing more evidence.",
        "bundle_shape": {
            "evidence_count": len(evidence),
            "allowed_evidence_count": len(allowed_ids),
            "source_count": len({source.get("id") for source in source_documents if source.get("id")}),
            "property_record_count": len({record.get("id") for record in property_records if record.get("id")}),
            "approx_evidence_json_bytes": _evidence_bytes(evidence),
            "detail_level": "full query evidence plus compact manifest and MCP expansion guidance",
        },
        "coverage": {
            "property_types": _counter_payload([str(record.get("property_type") or "unknown") for record in property_records]),
            "markets": _counter_payload([str(record.get("market") or "unknown") for record in property_records]),
            "source_types": _counter_payload([str(source.get("source_type") or "unknown") for source in source_documents]),
            "uploaders": _counter_payload([str(source.get("slack_user_name") or "unknown") for source in source_documents]),
        },
        "evidence_manifest": [_compact_evidence_item(item) for item in evidence],
        "source_manifest": _source_manifest(evidence),
        "available_backend_mcp_tools": BACKEND_MCP_TOOL_GUIDE,
        "recommended_mcp_calls": _recommended_mcp_calls(explain_payload),
    }


def build_backend_schema_context() -> dict[str, object]:
    return {
        "schema_version": "cre-backend-mcp-v2",
        "tables_exposed_by_tools": ["property_records", "source_documents", "chunks", "evidence_items", "answer_snapshots"],
        "property_filters": {
            "property_types": ["office", "industrial", "retail", "mixed_use", "land", "multifamily"],
            "address_terms": "array of normalized address fragments",
            "uploader_names": "array of Slack display names such as John, Sarah, Maya, Priya",
            "markets": "array of market/submarket fragments",
            "keywords": "array of terms matched against chunks, raw source text, address, and market",
            "price_per_sq_ft_lt": "numeric string or number",
            "price_per_sq_ft_gt": "numeric string or number",
            "sq_ft_gte": "integer minimum square footage",
            "sq_ft_lte": "integer maximum square footage",
            "availability_before": "ISO date string",
            "require_immediate": "boolean",
            "sort": ["price_asc", "size_desc", "availability_asc"],
            "limit": "integer; use 5-25 normally and expand only when the question is broad",
        },
        "coordinator_tools": {
            "summarize_inventory": "filters plus optional query_id; returns inventory group summaries and ranked slices",
            "rank_properties": "filters, objective, optional keywords, optional query_id; returns deterministic rank scores and reasons",
            "get_property_timeline": "property_ref plus optional query_id; returns all source-history rows for an address/property/duplicate group",
            "find_property_conflicts": "filters plus optional query_id and limit; returns duplicate groups with conflicting numeric/timing facts",
        },
        "aggregation": {
            "group_by": [None, "property_type", "market", "source_document", "uploader"],
            "metrics": ["count", "sum_sq_ft", "avg_sq_ft", "avg_price_per_sq_ft", "min_price_per_sq_ft", "max_price_per_sq_ft"],
        },
        "source_chunk_filters": ["property_types", "uploader_names", "source_types", "markets", "address_terms", "file_name_contains", "limit"],
        "safe_examples": [
            {"tool": "search_properties", "filters": {"property_types": ["industrial"], "price_per_sq_ft_lt": "35", "limit": 10}},
            {"tool": "aggregate_properties", "filters": {"property_types": ["office"]}, "group_by": "market", "metrics": ["count", "avg_price_per_sq_ft"]},
            {"tool": "expand_query_evidence", "filters": {"property_types": ["industrial"], "limit": 8}, "reason": "add comparable industrial options"},
            {"tool": "summarize_inventory", "filters": {"limit": 25}, "query_id": "current query id"},
            {"tool": "rank_properties", "filters": {"property_types": ["industrial"], "limit": 10}, "objective": "logistics tenant fit", "query_id": "current query id"},
            {"tool": "get_property_timeline", "property_ref": "Harbor Rd", "query_id": "current query id"},
            {"tool": "find_property_conflicts", "filters": {"limit": 50}, "query_id": "current query id", "limit": 10},
        ],
        "available_backend_mcp_tools": BACKEND_MCP_TOOL_GUIDE,
    }


__all__ = ["BACKEND_MCP_TOOL_GUIDE", "build_backend_schema_context", "build_evidence_context"]