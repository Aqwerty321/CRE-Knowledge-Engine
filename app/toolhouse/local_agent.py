from __future__ import annotations

from typing import Any

from app.answering.query_service import explain_query
from app.toolhouse.evidence_context import build_evidence_context


REQUIRED_RESPONSE_FIELDS = {
    "status",
    "rendered_answer",
    "cited_evidence_ids",
    "confidence_label",
    "reasoning_summary",
    "mcp_tools_used",
    "toolhouse_integrations_used",
    "slack_tools_used",
    "external_sources_consulted",
    "unsupported_claims_dropped",
    "missing_data",
    "suggested_followups",
}

ALLOWED_STATUSES = {
    "answered",
    "needs_more_evidence",
    "mcp_unavailable",
    "validation_risk",
    "tool_error",
    "external_context_only",
}

ALLOWED_CONFIDENCE_LABELS = {"high", "medium", "low"}

ALLOWED_MCP_TOOLS = {
    "describe_backend_schema",
    "expand_query_context",
    "expand_query_evidence",
    "explain_evidence",
    "explain_query",
    "find_property_conflicts",
    "get_property_timeline",
    "search_properties",
    "get_source_detail",
    "aggregate_properties",
    "search_source_chunks",
    "nearby_properties",
    "rank_properties",
    "summarize_inventory",
    "audit_data",
}

LIST_FIELDS = {
    "cited_evidence_ids",
    "mcp_tools_used",
    "toolhouse_integrations_used",
    "slack_tools_used",
    "external_sources_consulted",
    "unsupported_claims_dropped",
    "missing_data",
    "suggested_followups",
}

ALLOWED_EXTERNAL_SOURCE_ROLES = {"external_context_only", "document_inspection", "diagnostic"}


def _allowed_evidence_ids(explain_payload: dict[str, Any]) -> set[str]:
    return {str(item.get("evidence_id")) for item in explain_payload.get("evidence", []) if item.get("evidence_id")}


def _list_value(response_payload: dict[str, Any], field_name: str, schema_errors: list[str]) -> list[Any]:
    value = response_payload.get(field_name)
    if not isinstance(value, list):
        schema_errors.append(f"{field_name} must be an array")
        return []
    return value


def _string_value(response_payload: dict[str, Any], field_name: str, schema_errors: list[str]) -> str:
    value = response_payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        schema_errors.append(f"{field_name} must be a non-empty string")
        return ""
    return value


def _validate_comparison_table(response_payload: dict[str, Any], schema_errors: list[str]) -> None:
    table = response_payload.get("comparison_table")
    if table is None:
        return
    if not isinstance(table, dict):
        schema_errors.append("comparison_table must be an object when provided")
        return
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or len(columns) < 2:
        schema_errors.append("comparison_table.columns must be an array with at least 2 labels")
        return
    if not all(isinstance(value, str) and value.strip() for value in columns):
        schema_errors.append("comparison_table.columns must contain only non-empty strings")
    if not isinstance(rows, list) or len(rows) < 2:
        schema_errors.append("comparison_table.rows must be an array with at least 2 rows")
        return
    expected_width = len(columns)
    for index, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != expected_width:
            schema_errors.append(f"comparison_table.rows[{index}] must be an array with {expected_width} cells")
            continue
        if not all(isinstance(value, str) and value.strip() for value in row):
            schema_errors.append(f"comparison_table.rows[{index}] must contain only non-empty strings")


def validate_agent_response(
    *,
    allowed_evidence_ids: set[str],
    response_payload: dict[str, Any],
) -> dict[str, Any]:
    schema_errors: list[str] = []
    missing_fields = sorted(REQUIRED_RESPONSE_FIELDS - set(response_payload))
    if missing_fields:
        schema_errors.extend(f"missing required field: {field_name}" for field_name in missing_fields)

    status_value = response_payload.get("status")
    if status_value not in ALLOWED_STATUSES:
        schema_errors.append("status must be one of the supported Toolhouse result statuses")

    confidence_label = response_payload.get("confidence_label")
    if confidence_label not in ALLOWED_CONFIDENCE_LABELS:
        schema_errors.append("confidence_label must be high, medium, or low")

    _string_value(response_payload, "rendered_answer", schema_errors)
    _string_value(response_payload, "reasoning_summary", schema_errors)
    _validate_comparison_table(response_payload, schema_errors)

    for field_name in LIST_FIELDS:
        _list_value(response_payload, field_name, schema_errors)

    cited_values = _list_value(response_payload, "cited_evidence_ids", schema_errors)
    cited_ids = {str(value) for value in cited_values if isinstance(value, str) and value.strip()}
    if len(cited_ids) != len(cited_values):
        schema_errors.append("cited_evidence_ids must contain only non-empty strings")

    mcp_tool_values = _list_value(response_payload, "mcp_tools_used", schema_errors)
    mcp_tools = {str(value) for value in mcp_tool_values if isinstance(value, str) and value.strip()}
    if len(mcp_tools) != len(mcp_tool_values):
        schema_errors.append("mcp_tools_used must contain only non-empty strings")
    invalid_mcp_tools = sorted(mcp_tools - ALLOWED_MCP_TOOLS)
    if invalid_mcp_tools:
        schema_errors.append(f"mcp_tools_used contains unsupported tool names: {', '.join(invalid_mcp_tools)}")

    external_sources = _list_value(response_payload, "external_sources_consulted", schema_errors)
    for index, source in enumerate(external_sources):
        if not isinstance(source, dict):
            schema_errors.append(f"external_sources_consulted[{index}] must be an object")
            continue
        for field_name in ("title", "url", "role"):
            if not isinstance(source.get(field_name), str) or not source.get(field_name, "").strip():
                schema_errors.append(f"external_sources_consulted[{index}].{field_name} must be a non-empty string")
        if source.get("role") not in ALLOWED_EXTERNAL_SOURCE_ROLES:
            schema_errors.append(f"external_sources_consulted[{index}].role is unsupported")

    if status_value == "answered" and not cited_ids:
        schema_errors.append("answered responses must cite at least one allowed evidence ID")
    if status_value == "answered" and not mcp_tools:
        schema_errors.append("answered responses must include at least one MCP tool in mcp_tools_used")

    invalid_ids = sorted(cited_ids - allowed_evidence_ids)
    return {
        "valid": not invalid_ids and not schema_errors,
        "allowed_evidence_count": len(allowed_evidence_ids),
        "cited_evidence_count": len(cited_ids),
        "invalid_evidence_ids": invalid_ids,
        "schema_errors": schema_errors,
    }


def _format_property_fact(property_record: dict[str, Any] | None) -> str:
    if property_record is None:
        return "source detail unavailable"
    address = property_record.get("address") or "Unknown address"
    sq_ft = property_record.get("sq_ft")
    price = property_record.get("price_per_sq_ft")
    availability = property_record.get("availability") or "availability unknown"
    sq_ft_label = "unknown SF" if sq_ft is None else f"{int(sq_ft):,} SF"
    price_label = "unknown price" if price is None else f"${price}/SF"
    return f"{address} - {sq_ft_label} at {price_label}, {availability}"


def _build_comparison_table_from_evidence(evidence: list[dict[str, Any]]) -> dict[str, Any] | None:
    rows: list[list[str]] = []
    for item in evidence[:5]:
        property_record = dict(item.get("property_record") or {})
        if not property_record:
            continue
        sq_ft = property_record.get("sq_ft")
        price = property_record.get("price_per_sq_ft")
        rows.append(
            [
                str(property_record.get("address") or "-"),
                "unknown SF" if sq_ft is None else f"{int(sq_ft):,} SF",
                "unknown price" if price is None else f"${price}/SF",
                str(property_record.get("availability") or "-"),
            ]
        )
    if len(rows) < 2:
        return None
    return {"title": "Quick comparison", "columns": ["Addr", "SF", "Rent", "Avail"], "rows": rows}


def _render_local_deeper_answer(explain_payload: dict[str, Any]) -> dict[str, Any]:
    evidence = list(explain_payload.get("evidence", []))
    query_text = str(explain_payload.get("query_text") or "the question")
    if not evidence:
        return {
            "status": "needs_more_evidence",
            "rendered_answer": (
                "*Deeper review*\n"
                "I still do not have sourced evidence for that.\n"
                "_The clean move is to widen ingestion or add the missing Slack source before trusting an answer._"
            ),
            "cited_evidence_ids": [],
            "confidence_label": "low",
            "reasoning_summary": "Local fallback found no backend evidence IDs for the query package.",
            "mcp_tools_used": ["explain_evidence"],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [],
            "unsupported_claims_dropped": ["Any stronger CRE claim was withheld because no backend evidence IDs were available."],
            "missing_data": ["Backend evidence for the query."],
            "suggested_followups": ["Ingest or expose the missing source, then rerun Look deeper."],
        }

    decision_summary = explain_payload.get("decision_summary") or {}
    first = evidence[0]
    first_fact = _format_property_fact(first.get("property_record"))
    lines = ["*Deeper review*", f"*Query:* {query_text}", f"*Top read:* {first_fact}"]

    if decision_summary:
        selection_reason = decision_summary.get("selection_reason")
        if selection_reason:
            lines.append(f"*Why it leads:* {str(selection_reason).rstrip('.')}.")

    lines.append("*Evidence checked:*")
    for item in evidence[:3]:
        summary = item.get("source_summary") or "Unknown source"
        role = item.get("evidence_role") or "supporting"
        lines.append(f"- *{str(role).replace('_', ' ').title()}* - {summary}")

    if len(evidence) > 3:
        lines.append(f"- *Additional support* - {len(evidence) - 3} more source(s) kept in the evidence bundle.")

    lines.append("_Evidence-bound local synthesis. Toolhouse can reason over this same bundle next._")
    return {
        "status": "answered",
        "rendered_answer": "\n".join(lines),
        "comparison_table": _build_comparison_table_from_evidence(evidence),
        "cited_evidence_ids": [str(item.get("evidence_id")) for item in evidence[:3] if item.get("evidence_id")],
        "confidence_label": "medium",
        "reasoning_summary": "Local fallback summarized the stored backend evidence bundle and cited allowed evidence IDs.",
        "mcp_tools_used": ["explain_evidence"],
        "toolhouse_integrations_used": [],
        "slack_tools_used": [],
        "external_sources_consulted": [],
        "unsupported_claims_dropped": [],
        "missing_data": [],
        "suggested_followups": ["Use Toolhouse MCP for a richer multi-source comparison when live credentials are available."],
    }


async def build_escalation_payload(query_id: str) -> dict[str, Any]:
    explain_payload = await explain_query(query_id)
    if explain_payload.get("status") != "explained":
        return {
            "status": "not_ready",
            "query_id": query_id,
            "message": explain_payload.get("message") or "No explainable query payload was found.",
            "explain_payload": explain_payload,
        }

    allowed_evidence_ids = sorted(_allowed_evidence_ids(explain_payload))
    evidence_context = build_evidence_context(explain_payload, allowed_evidence_ids=allowed_evidence_ids)
    return {
        "status": "ready",
        "query_id": query_id,
        "original_query": explain_payload.get("query_text"),
        "heuristic_result": explain_payload.get("answer_snapshot", {}).get("rendered_answer"),
        "route_mode": explain_payload.get("route_mode"),
        "reason_codes": explain_payload.get("reason_codes", []),
        "filters": explain_payload.get("answer_snapshot", {}).get("filters", {}),
        "allowed_evidence_ids": allowed_evidence_ids,
        "evidence": explain_payload.get("evidence", []),
        "evidence_context": evidence_context,
        "backend_mcp_tools": evidence_context["available_backend_mcp_tools"],
        "slack_context": explain_payload.get("slack_context", {}),
        "decision_summary": explain_payload.get("decision_summary"),
        "explain_payload": explain_payload,
    }


async def run_local_deeper_review(query_id: str) -> dict[str, Any]:
    escalation_payload = await build_escalation_payload(query_id)
    if escalation_payload.get("status") != "ready":
        return {
            "status": "not_ready",
            "answer_mode": "agent_mode",
            "query_id": query_id,
            "rendered_answer": str(escalation_payload.get("message") or "No local evidence bundle is available."),
            "validation": {"valid": False, "invalid_evidence_ids": []},
            "escalation_payload": escalation_payload,
        }

    local_response = _render_local_deeper_answer(dict(escalation_payload["explain_payload"]))
    validation = validate_agent_response(
        allowed_evidence_ids=set(escalation_payload["allowed_evidence_ids"]),
        response_payload=local_response,
    )
    if not validation["valid"]:
        return {
            "status": "validation_failed",
            "answer_mode": "agent_mode",
            "query_id": query_id,
            "rendered_answer": "Deeper review failed citation validation, so I am not posting it.",
            "validation": validation,
            "escalation_payload": escalation_payload,
        }

    return {
        "status": str(local_response.get("status") or "answered"),
        "answer_mode": "agent_mode",
        "query_id": query_id,
        "rendered_answer": local_response["rendered_answer"],
        "comparison_table": local_response.get("comparison_table"),
        "cited_evidence_ids": local_response["cited_evidence_ids"],
        "validation": validation,
        "dependency_state": {"toolhouse": False, "local_deeper_review": True, "llm": False},
        "escalation_payload": escalation_payload,
    }


__all__ = ["build_escalation_payload", "run_local_deeper_review", "validate_agent_response"]
