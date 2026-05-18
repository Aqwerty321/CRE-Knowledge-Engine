# Toolhouse Readiness Checkpoint

## Status

The project is now ready for bounded Toolhouse integration.

That means Toolhouse can be connected as the synthesis and orchestration layer, while the backend remains the source of truth for retrieval, citations, and validation.

The system is not yet claiming broad autonomous Slack ingestion or production-grade semantic retrieval. Those can follow after the first real Toolhouse path is live.

## What Changed In This Hardening Slice

### Broader Heuristic Answering

The router now keeps the original golden paths and adds a general heuristic query-constructor layer:

- [app/routing/query_constructor.py](../app/routing/query_constructor.py) parses property type, address, uploader, market, price, square footage, availability, aggregation, tenant-fit, and missing-data intent.
- [app/retrieval/structured_service.py](../app/retrieval/structured_service.py) turns those parsed filters into a deterministic PostgreSQL query constructor.
- [app/answering/query_service.py](../app/answering/query_service.py) renders generic structured search, exact lookup, aggregation, tenant-fit, no-result, and data-quality answers.

Useful local examples:

```bash
uv run cre-cli ask 'Show industrial listings over 30k SF under $25/SF.'
uv run cre-cli ask 'What do we know about 700 Logistics Pkwy?'
uv run cre-cli ask 'Which options look best for a logistics tenant under $35/SF?'
uv run cre-cli ask 'What source data is missing from the indexed corpus?'
```

### Query Constructor Metadata

Instant and local synthesis answers now preserve a `query_constructor` object in the answer snapshot filters.

That object includes:

- base table;
- joins;
- conditions;
- sort;
- limit.

This is the bridge between heuristic instant mode and future Toolhouse tools. If Toolhouse asks why a local answer exists, the backend can show the exact structured query shape that produced it.

### Missing-Data Explainability

No-result answers now include a `missing_data_explanation` when the backend can explain what blocked the query.

Example behavior:

- user asks for office listings under a price threshold that has no match;
- backend reports the applied filters;
- backend returns closest matches after relaxing numeric/date filters;
- the explanation is persisted in the answer snapshot.

There is also a new data audit command:

```bash
uv run cre-cli audit-data
```

Current live-synced audit result:

- 14 source documents;
- 14 structured property records;
- 0 sources without chunks;
- 3 sources with text but no extracted property rows;
- 0 missing source URLs on property-backed records after live Slack sync;
- 1 explainable conflict group for Harbor Rd;
- `toolhouse_readiness.status = ready_for_bounded_agent`.

### Hardened Importer

[app/ingestion/sample_importer.py](../app/ingestion/sample_importer.py) now emits validation warnings for:

- duplicate source IDs;
- missing source text;
- duplicate chunk indexes;
- sources without extracted property rows;
- property rows that point at missing chunks;
- missing structured property fields.

The importer also stores broader field-level provenance for default field values, including normalized address, property type, availability date, market, and geo coordinates.

### Local `Look deeper`

Slack answers now include both:

- `Show sources`;
- `Look deeper`.

The `Look deeper` action:

- immediately posts `On it. Checking the messy bits.` as an ephemeral acknowledgement;
- queues a `look_deeper` job;
- packages the stored query and allowed evidence bundle;
- runs a local evidence-bound deeper review;
- validates cited evidence IDs before posting;
- posts the result in the original thread.

This is intentionally local for now. The point is to prove the boundary before wiring real Toolhouse credentials.

### Toolhouse-Facing Backend Tools

[app/toolhouse/tools.py](../app/toolhouse/tools.py) now exposes deterministic backend tool functions:

- `explain_evidence_tool(query_id)`;
- `explain_query_tool(query_id)`;
- `search_properties_tool(filters)`;
- `get_source_detail_tool(source_id)`;
- `aggregate_properties_tool(filters, group_by, metrics)`;
- `search_source_chunks_tool(query, filters)`;
- `nearby_properties_tool(origin, radius_miles, filters)`;
- `audit_data_tool()`;
- `local_deeper_review_tool(query_id)`.

These tools return structured payloads with evidence IDs from query explanation, source metadata, query-constructor details, chunks, property records, aggregations, keyword chunk results, proximity rankings, and data-quality state. They are now exposed through the read-only CRE Backend MCP endpoint for Toolhouse.

### Authenticated MCP Endpoint

[app/toolhouse/mcp_server.py](../app/toolhouse/mcp_server.py) now exposes those functions through a read-only FastMCP server.

Runtime shape:

- mounted into FastAPI at `/toolhouse/mcp`;
- Streamable HTTP MCP transport;
- protected by `Authorization: Bearer <CRE_TOOLHOUSE_MCP_BEARER_TOKEN>`;
- also accepts `?mcp_token=<CRE_TOOLHOUSE_MCP_BEARER_TOKEN>` for URL-only Toolhouse MCP setup;
- returns `503 mcp_auth_not_configured` if `CRE_TOOLHOUSE_MCP_BEARER_TOKEN` is missing;
- returns `401 unauthorized` when the bearer token is missing or wrong.

### Toolhouse Workers API Client

[app/toolhouse/client.py](../app/toolhouse/client.py) now stores the current Toolhouse Agent ID and implements the Workers API call path.

Runtime shape:

- current Toolhouse Agent ID: `0c2c4555-5d96-47e4-8e05-f956de7a102e`;
- first message uses `POST https://agents.toolhouse.ai/$AGENT_ID`;
- continuation uses `PUT https://agents.toolhouse.ai/$AGENT_ID/$RUN_ID`;
- auth uses `CRE_TOOLHOUSE_API_KEY`;
- backend saves `X-Toolhouse-Run-ID` when returned;
- streamed chunks are collected and parsed into the strict JSON response contract;
- `Look deeper` uses Toolhouse when configured and preserves the local fallback when config or transport is missing.

The remaining live integration step is Toolhouse-side MCP connection and setting local secrets.

### Agent Run Traceability

Toolhouse and local deeper-review attempts now persist a dedicated `agent_runs` trace row.

Each trace records:

- original `query_id`;
- provider path (`toolhouse`, `local`, or `local_fallback`);
- allowed and cited evidence IDs;
- Toolhouse agent and run IDs when available;
- raw Toolhouse response and parsed response payload;
- validation result, dependency state, fallback reason, and final rendered answer.

This keeps agent behavior replayable without mixing long-lived synthesis traces into generic job checkpoints.

### Operator Visibility

`/health/deps` now reports:

- database state;
- Qdrant config state;
- Slack config state;
- Toolhouse config state;
- background worker enabled/disabled state;
- ingestion and Slack job counts by type/status.

## Current Validation

Full test suite:

```bash
uv run pytest -q
```

Current result:

- 81 passed;
- no known failures or warning noise.

Graphify was also rebuilt after this slice:

- 549 nodes;
- 928 edges;
- 45 communities.

Focused new coverage includes:

- broad structured numeric filters;
- exact property lookup;
- no-result missing-data explanations;
- data-quality query answers;
- local tenant-fit synthesis;
- Slack `Look deeper` action and worker processing;
- deterministic Toolhouse-facing tools.
- authenticated MCP endpoint registration and auth;
- Toolhouse Workers API streaming response parsing;
- Toolhouse response citation and output-contract validation;
- persisted `agent_runs` traces for valid Toolhouse responses and validated fallback paths;
- Slack source-post provenance for repeated file shares across channels;
- stricter Toolhouse response-contract tests for malformed tables, unsupported tools, and external source roles;
- local fallback when Toolhouse returns an invalid answer contract;
- live Toolhouse smoke command;
- mounted FastMCP lifespan initialization inside the parent FastAPI app;
- public Cloudflare host allowance for Toolhouse MCP calls;
- generic Slack message event ACKs so Slack does not retry ordinary channel chatter as 404s.

## Toolhouse Connected State

Local secrets are set, the backend is running on the demo port, the Cloudflare tunnel reaches `/health/deps`, and the public MCP URL reaches the backend with URL-token auth.

The latest live Toolhouse smoke run used `uv run cre-cli toolhouse-smoke` and returned:

- status: `answered`;
- Toolhouse fallback: `false`;
- validation: `valid` with no invalid evidence IDs and no schema errors;
- allowed evidence count: 4;
- cited evidence count: 4.

The first real Toolhouse slice now keeps the existing boundary:

1. keep Slack `Look deeper` unchanged;
2. keep `build_escalation_payload(query_id)` unchanged;
3. send the bounded payload to Toolhouse through the Workers API when credentials are configured;
4. let Toolhouse call the CRE Backend MCP server;
5. validate Toolhouse citations against allowed evidence IDs;
6. post only validated output.

## Still Deferred After Toolhouse Starts

These are not blockers for the first Toolhouse demo:

- full Slack continuous backfill;
- broad file-event ingestion;
- Qdrant semantic retrieval as the default hybrid path;
- multi-user Slack permission semantics;
- production auth around future external tool endpoints;

The important invariant is already in place: Toolhouse should synthesize only over backend-provided evidence, and the backend should reject unsupported citations.
