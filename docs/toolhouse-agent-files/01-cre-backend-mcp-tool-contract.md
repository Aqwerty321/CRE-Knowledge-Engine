# CRE Backend MCP Tool Contract

Use this file as a Toolhouse Agent File for the `CRE MCP Look Deeper Analyst` worker.

## Purpose

The CRE Backend MCP server is the mandatory fact and evidence surface for the Toolhouse worker. Toolhouse may synthesize, compare, and explain. It must not become the source of truth.

The backend owns:

- Slack intake and acknowledgement;
- durable jobs and retries;
- Postgres evidence and source records;
- deterministic retrieval and calculations;
- citation validation;
- final Slack posting.

The Toolhouse worker owns:

- deeper synthesis over backend evidence;
- multi-source comparison;
- plain-English risk and confidence explanation;
- structured JSON output for backend validation.

## Server And Auth Expectations

- MCP server name: `CRE Backend MCP`.
- MCP transport: Streamable HTTP from the official Python MCP SDK.
- Local mounted path: `/toolhouse/mcp` on the existing FastAPI backend.
- Public demo URL shape: `https://<public-backend-host>/toolhouse/mcp`.
- Tool behavior: read-only.
- Tool authentication: `Authorization: Bearer <CRE_TOOLHOUSE_MCP_BEARER_TOKEN>`.
- URL-only Toolhouse setup can use `https://<public-backend-host>/toolhouse/mcp?mcp_token=<CRE_TOOLHOUSE_MCP_BEARER_TOKEN>` if the UI does not expose an auth-header field.
- Required backend env var: `CRE_TOOLHOUSE_MCP_BEARER_TOKEN`.
- Toolhouse must not receive direct database credentials.
- Toolhouse must not mutate records, Slack messages, files, or source documents.
- If the MCP server is unavailable, return `mcp_unavailable` in the worker output.

The backend returns `503 mcp_auth_not_configured` if the MCP bearer token is not set, and `401 unauthorized` if the bearer token is missing or wrong. Use a dedicated MCP token, not the Toolhouse Workers API key, in MCP URL or header auth.

## Tool Naming

Expose the public MCP tools without the Python `_tool` suffix.

Current backend wrappers implemented in `app/toolhouse/tools.py`:

- `explain_evidence`
- `explain_query`
- `search_properties`
- `get_source_detail`
- `aggregate_properties`
- `search_source_chunks`
- `nearby_properties`
- `audit_data`

Current local-only helper, useful for tests but not the real Toolhouse worker:

- `local_deeper_review`

## Common Object Shapes

### Source Document

```json
{
  "id": "uuid",
  "source_type": "slack_message | slack_thread_reply | pdf | csv | xlsx | text",
  "file_name": "industrial-availability.csv",
  "source_url": "https://...",
  "local_path": "files/industrial-availability.csv",
  "slack_user_name": "Priya",
  "slack_channel_name": "cre-listings",
  "slack_ts": "1715590800.000100",
  "posted_at": "2026-05-13T09:00:00+00:00"
}
```

### Property Record

```json
{
  "id": "uuid",
  "address": "88 Foundry Ln",
  "normalized_address": "88 foundry ln",
  "property_type": "industrial",
  "sq_ft": 44000,
  "price_per_sq_ft": "21.50",
  "availability": "Q2 2026",
  "availability_date": "2026-04-01",
  "market": "Harbor District",
  "source_page": null,
  "source_row": 2,
  "source_authority_score": "0.9700",
  "freshness_score": "0.8400",
  "duplicate_group_key": "88 foundry ln|industrial"
}
```

### Chunk

```json
{
  "id": "uuid",
  "chunk_index": 0,
  "page_number": null,
  "row_number": 2,
  "section_name": "Rows 2-4",
  "text_preview": "Short source excerpt."
}
```

### Evidence Item

```json
{
  "evidence_id": "uuid",
  "relevance_score": "0.9300",
  "matched_fields": ["property_type", "sq_ft", "price_per_sq_ft"],
  "source_summary": "industrial-availability.csv (row 2; Priya; #cre-listings; 2026-05-13)",
  "source_document": {},
  "property_record": {},
  "chunk": {},
  "field_details": [],
  "evidence_role": "selected | candidate | supporting | superseded | result",
  "selection_reason": "Why the backend selected or ranked this evidence."
}
```

## Tool Contracts

### `explain_evidence`

Status: implemented now.

Input:

```json
{"query_id": "uuid"}
```

Output:

```json
{
  "tool": "explain_evidence",
  "status": "ready | not_ready",
  "payload": {
    "status": "ready",
    "query_id": "uuid",
    "original_query": "User question",
    "heuristic_result": "Local backend answer text",
    "route_mode": "instant | hybrid | agentic | failed",
    "reason_codes": ["heuristic_router"],
    "filters": {},
    "allowed_evidence_ids": ["uuid"],
    "evidence": [],
    "decision_summary": {},
    "explain_payload": {}
  }
}
```

Usage rule: call this first for every task with `query_id`. Build the allowed citation set from `allowed_evidence_ids` and later MCP tool results that explicitly return evidence IDs.

### `explain_query`

Status: implemented now.

Input:

```json
{"query_id": "uuid"}
```

Output:

```json
{
  "tool": "explain_query",
  "status": "ok",
  "payload": {
    "status": "explained | invalid_query_id | not_found",
    "query_id": "uuid",
    "query_text": "User question",
    "route_mode": "instant | hybrid | agentic | failed",
    "route_confidence": "0.9000",
    "reason_codes": [],
    "answer_snapshot": {
      "filters": {},
      "dependency_state": {},
      "model_versions": {},
      "evidence_ids": [],
      "rendered_answer": "Slack-visible answer"
    },
    "evidence_count": 0,
    "evidence": [],
    "source_summaries": [],
    "decision_summary": {},
    "missing_data_explanation": null,
    "data_quality_report": null
  }
}
```

Usage rule: use when route mode, filters, answer provenance, missing-data explanation, or decision summary matters.

### `search_properties`

Status: implemented now.

Input:

```json
{
  "filters": {
    "intent": "property_search | exact_lookup | aggregation | tenant_fit | data_completeness",
    "property_types": ["industrial"],
    "address_terms": ["88 foundry ln"],
    "uploader_names": ["Priya"],
    "markets": ["Harbor District"],
    "keywords": ["loading dock", "yard", "logistics"],
    "price_per_sq_ft_lt": "25",
    "price_per_sq_ft_gt": null,
    "sq_ft_gte": 30000,
    "sq_ft_lte": null,
    "availability_before": "2026-08-31",
    "require_immediate": false,
    "aggregate": null,
    "aggregate_field": null,
    "sort": "price_asc | size_desc | availability_asc | tenant_fit",
    "limit": 5
  }
}
```

Output:

```json
{
  "tool": "search_properties",
  "status": "ok",
  "query_constructor": {
    "base_table": "property_records",
    "joins": [],
    "conditions": [],
    "sort": [],
    "limit": 5
  },
  "result_count": 0,
  "results": [
    {
      "property_record": {},
      "source_document": {},
      "chunk": {},
      "matched_fields": [],
      "relevance_score": "0.9300",
      "selection_reason": "structured query constructor match"
    }
  ]
}
```

Usage rule: use for broader structured matching, relaxed filters, tenant-fit candidate retrieval, exact address lookup, and source/uploader filters. Do not invent records that are not returned.

### `get_source_detail`

Status: implemented now.

Input:

```json
{"source_id": "uuid"}
```

Output:

```json
{
  "tool": "get_source_detail",
  "status": "ok | invalid_source_id | not_found",
  "source_document": {},
  "chunks": [],
  "property_records": []
}
```

Usage rule: call before making a specific claim about a source document, file, Slack message, row, page, or extracted property row.

### `aggregate_properties`

Status: implemented now.

Input:

```json
{
  "filters": {},
  "group_by": "property_type | market | source_document | null",
  "metrics": ["count", "sum_sq_ft", "avg_price_per_sq_ft", "min_price_per_sq_ft", "max_price_per_sq_ft"]
}
```

Output:

```json
{
  "tool": "aggregate_properties",
  "status": "ok",
  "rows": [],
  "evidence_ids": [],
  "evidence_note": "This read-only tool does not mint query evidence IDs; cite IDs from explain_evidence or backend-validated query evidence.",
  "query_constructor": {}
}
```

Usage rule: use this for all user-facing counts, sums, averages, min/max values, and ranges.

### `search_source_chunks`

Status: implemented now.

Input:

```json
{"query": "loading docks yard space", "filters": {}}
```

Output:

```json
{
  "tool": "search_source_chunks",
  "status": "ok",
  "result_count": 0,
  "results": [
    {
      "source_document": {},
      "chunk": {},
      "property_record": {},
      "matched_terms": [],
      "relevance_score": "0.9000"
    }
  ]
}
```

Usage rule: use for narrative source text, market reports, tenant requirements, and concepts not captured in structured fields.

### `nearby_properties`

Status: implemented now.

Input:

```json
{
  "origin": "120 Main St",
  "radius_miles": 2.0,
  "filters": {"property_types": ["office"], "limit": 5}
}
```

Output:

```json
{
  "tool": "nearby_properties",
  "status": "ok",
  "origin": {},
  "results": [
    {
      "distance_miles": 0.7,
      "property_record": {},
      "source_document": {},
      "chunk": {},
      "matched_fields": ["geo_lat", "geo_lng"]
    }
  ]
}
```

Usage rule: use this for proximity and radius questions. Do not calculate distance yourself for final claims.

### `audit_data`

Status: implemented now.

Input:

```json
{}
```

Output:

```json
{
  "tool": "audit_data",
  "status": "ok",
  "source_document_count": 14,
  "property_record_count": 14,
  "sources_without_chunks": [],
  "sources_without_properties": [],
  "missing_field_counts": {},
  "conflict_groups": [],
  "toolhouse_readiness": {"status": "ready_for_bounded_agent"}
}
```

Usage rule: use for missing-data, readiness, corpus completeness, and quality questions.

## Error Handling

If a tool returns `invalid_query_id`, `invalid_source_id`, `not_found`, `not_ready`, or a transport error:

1. Do not answer from general knowledge.
2. Explain the precise blocker in `missing_data` or `reasoning_summary`.
3. Use `mcp_unavailable`, `tool_error`, or `needs_more_evidence` as the output status.
4. Do not cite evidence IDs not returned by MCP.
