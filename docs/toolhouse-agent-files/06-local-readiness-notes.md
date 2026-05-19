# Local Readiness Notes

Upload this file when Toolhouse Agent Builder asks for local readiness notes.

## Current Status

The CRE Knowledge Engine backend is ready for a bounded Toolhouse worker integration.

Toolhouse should act as the deeper-analysis worker. The local backend remains the source of truth for Slack intake, queued jobs, Postgres evidence, deterministic retrieval, citation validation, and final Slack posting.

## Date And Demo Context

- Current readiness date: 2026-05-19.
- Demo reference date for availability parsing: 2026-05-17.
- Slack request mode: HTTP Events API / interactivity, not Socket Mode.
- Slack `Look deeper` behavior: backend ACKs immediately, queues work, validates the agent response, then posts to the original thread.
- Slack `/force-agent` behavior: backend queues Toolhouse directly, still persists a replayable query package, and validates citations before posting.
- Slack `Follow Up with Agent ⚡` behavior: backend opens a modal immediately, persists `ThreadSession` state by channel/thread, displays cached suggestions when they exist, shows `Generate suggestions` when the cache is empty, and routes custom follow-ups through `Instant`, default `Auto`, or `Agent` mode radio buttons.
- Suggested follow-up behavior: Toolhouse may generate allowed `{kind, question}` options during answer tasks or explicit `task=suggest_followups` generate/refresh actions; the backend preserves unanswered cached suggestions, attaches prevalidated SQL templates, marks selected suggestions answered, and runs selected suggestions in guaranteed `Instant` mode.

## MCP Server And Backend Tool Surface

The CRE Backend MCP server is now mounted into the existing FastAPI app.

- MCP server name: `CRE Backend MCP`.
- Local mounted path: `/toolhouse/mcp`.
- Public demo URL shape: `https://<public-backend-host>/toolhouse/mcp`.
- Auth header: `Authorization: Bearer <CRE_TOOLHOUSE_MCP_BEARER_TOKEN>`.
- URL-only Toolhouse setup: `https://<public-backend-host>/toolhouse/mcp?mcp_token=<CRE_TOOLHOUSE_MCP_BEARER_TOKEN>`.
- Required env var: `CRE_TOOLHOUSE_MCP_BEARER_TOKEN`.
- Health visibility: `/health/deps` reports `toolhouse_mcp` as `configured` when the token is set.

The application-level Toolhouse functions are implemented in `app/toolhouse/tools.py`, exposed through `app/toolhouse/mcp_server.py`, and exported from `app/toolhouse/__init__.py` where appropriate.

Implemented tools:

- `explain_evidence(query_id)`: returns the escalation payload, local answer, allowed evidence IDs, evidence bundle, filters, and decision summary.
- `explain_query(query_id)`: returns route mode, reason codes, answer snapshot, query constructor, evidence, missing-data explanation, and data-quality report when available.
- `describe_backend_schema()`: returns supported filters, sort modes, aggregation metrics, coordinator tool guidance, and safe examples.
- `expand_query_context(query_id, include_source_details, max_sources)`: returns richer source details, aggregate summaries, evidence context, and allowed evidence IDs for an existing query.
- `expand_query_evidence(query_id, filters, reason)`: asks the backend to mint additional evidence IDs for the same query through controlled structured retrieval.
- `summarize_inventory(filters, query_id)`: returns type/market inventory summaries and cheapest/largest/soonest ranked slices; ranked slices mint query evidence when `query_id` is present.
- `rank_properties(filters, objective, keywords, query_id)`: ranks structured property matches for objectives like logistics fit, cheapest, largest, available soon, or balanced review.
- `get_property_timeline(property_ref, query_id)`: traces one address/property/duplicate group across source history and can attach query evidence IDs.
- `find_property_conflicts(filters, query_id, limit)`: finds duplicate property groups with conflicting size, rent, or availability and can expand query evidence for those records.
- `search_properties(filters)`: deterministic structured property retrieval over normalized Postgres records.
- `get_source_detail(source_id)`: source metadata, chunks, and property rows for a source document.
- `aggregate_properties(filters, group_by, metrics)`: backend-computed counts, square-footage totals, average square footage, average rent, and min/max rent by optional group.
- `search_source_chunks(query, filters)`: keyword chunk search over source text, raw text, file names, and joined property records.
- `nearby_properties(origin, radius_miles, filters)`: backend Haversine proximity ranking from coordinates or a known property address.
- `audit_data()`: corpus completeness, missing fields, conflict groups, and Toolhouse readiness state.

Local-only helper:

- `local_deeper_review(query_id)`: deterministic fallback when Toolhouse credentials are missing, transport/parsing fails, or the live worker returns an invalid output contract.

## Toolhouse Worker API Connection

Current Toolhouse Agent ID:

```text
0c2c4555-5d96-47e4-8e05-f956de7a102e
```

Runtime settings:

- `CRE_TOOLHOUSE_AGENT_ID=0c2c4555-5d96-47e4-8e05-f956de7a102e`
- `CRE_TOOLHOUSE_API_KEY=<Toolhouse Workers API key>`
- `CRE_TOOLHOUSE_MCP_BEARER_TOKEN=<separate MCP token>`

Do not store the Toolhouse API key in tracked docs or source files.

Worker API behavior implemented locally:

- first message: `POST https://agents.toolhouse.ai/0c2c4555-5d96-47e4-8e05-f956de7a102e` with JSON body `{ "message": "<backend query package JSON>" }`;
- continuation message: `PUT https://agents.toolhouse.ai/0c2c4555-5d96-47e4-8e05-f956de7a102e/<run_id>` with the same body shape;
- auth header: `Authorization: Bearer <CRE_TOOLHOUSE_API_KEY>`;
- returned run ID header: `X-Toolhouse-Run-ID`;
- response body streams in chunks;
- backend collects chunks, extracts the final strict JSON object, validates the output contract and citations, and posts only validated content.

Toolhouse task modes now expected by the backend:

- `look_deeper`: richer analysis over an existing backend answer.
- `force_agent`: direct Toolhouse path that bypasses local instant routing but preserves backend citation validation.
- `follow_up_agent`: custom follow-up that needs Toolhouse over accumulated `ThreadSession` evidence and coverage gaps.
- `suggest_followups`: lightweight modal-support task that returns only 3-5 allowed `{kind, question}` objects; backend owns the attached SQL templates.

## Citation Readiness

The backend already validates Toolhouse-style responses with `validate_agent_response(...)`.

Rules:

- The worker may cite only evidence IDs returned by `explain_evidence` or another backend-validated query evidence path.
- Broad read-only tools such as `aggregate_properties`, `search_source_chunks`, `nearby_properties`, and `search_properties` return supporting source/property context but do not mint new query evidence IDs by themselves.
- `expand_query_evidence`, `summarize_inventory`, `rank_properties`, `get_property_timeline`, and `find_property_conflicts` can return query-scoped evidence IDs when `query_id` is provided. Those IDs become valid only after backend validation refresh.
- If a tool uncovers useful context that is not in the allowed evidence set and has no query-scoped evidence ID, the worker should call an evidence-expanding backend tool or mark the claim as needing more evidence.
- The backend rejects unsupported citations and invalid Toolhouse output contracts before posting to Slack.

## Current Data Readiness

Latest known audit state:

- 23 source documents.
- 25 structured property records.
- 0 sources without chunks.
- 3 sources with text but no extracted property rows.
- 6 local Slack-shaped message rows without source URLs before live permalink overlay.
- 1 explainable Harbor Rd conflict group.
- `toolhouse_readiness.status = ready_for_bounded_agent`.

Meaning:

- Good enough for bounded Toolhouse `Look deeper` demos.
- Not claiming complete autonomous Slack ingestion yet.
- Sources without property rows can be context, not structured fact authority.

## Validation State

Focused Toolhouse backend and MCP validation passes:

```bash
uv run pytest tests/test_toolhouse_client.py tests/test_toolhouse_tools.py tests/test_toolhouse_mcp_server.py -q
```

Validated behavior includes:

- evidence explanation;
- local deeper-review citation and output-contract validation;
- structured property search;
- source detail lookup;
- aggregation;
- inventory summaries;
- backend-owned ranking;
- property timeline tracing;
- conflict discovery;
- source chunk search;
- proximity ranking;
- data audit readiness.
- MCP tool registration;
- MCP bearer-token enforcement.
- URL-token MCP setup for URL-only clients;
- Toolhouse streaming response parsing.
- live Toolhouse smoke command: `uv run cre-cli toolhouse-smoke`.

Current full suite:

```bash
uv run pytest -q
```

Current result: tests pass with no known failures or warning noise.

Latest full-suite count after ThreadSession, follow-up modal, suggested follow-up work, cached answer-task suggestions, refresh, and modal exclusivity updates: 118 tests passing.

Latest focused Toolhouse/MCP count after coordinator pass: 20 tests passing.

Latest live Toolhouse smoke:

- command: `uv run cre-cli toolhouse-smoke`;
- status: `answered`;
- Toolhouse fallback: `false`;
- validation: valid, with no invalid evidence IDs and no schema errors;
- evidence: 4 allowed IDs and 4 cited IDs.

## Still Required Before Live Demo Use

Remaining operator steps:

1. Keep the FastAPI backend running on `CRE_PORT`.
2. Keep the HTTP/2 Cloudflare tunnel running from the user config.
3. Keep local fallback enabled until live Slack runs are stable.
4. Reuse backend citation validation before Slack posting.

## Deliberately Deferred

These are not blockers for the first Toolhouse worker:

- Redis-backed queueing.
- Dedicated `agent_runs` table.
- Qdrant as the default retrieval path.
- Full continuous Slack backfill.
- Broad Slack write/admin tools inside Toolhouse.
- Worker Email.
- Toolhouse Schedules.
- Image generation or editing.

## Operational Invariant

The correct first live demo is:

1. Backend answers fast with sources.
2. User clicks `Look deeper`.
3. Backend sends a grounded package to Toolhouse.
4. Toolhouse calls CRE Backend MCP tools.
5. Toolhouse returns strict JSON.
6. Backend validates the output contract and cited evidence IDs.
7. Backend posts only validated content to Slack.

The direct follow-up variant is:

1. User sends `/force-agent <question>`.
2. Backend skips the instant router but still creates a replayable query package.
3. Toolhouse starts from backend MCP and Slack context.
4. Backend validates citations and posts the result to Slack.

The modal follow-up variant is:

1. User clicks `Follow Up with Agent ⚡`.
2. Backend opens the modal immediately and first uses still-relevant unanswered suggestions cached from previous Toolhouse answer runs.
3. If no cache exists, the modal button reads `Generate suggestions`; clicking it forces a lightweight Toolhouse `suggest_followups` request for question wording only.
4. If suggestions already exist, the button reads `Refresh suggestions`; clicking it forces a fresh `suggest_followups` pass while preserving unanswered cached options.
5. Backend stores allowed suggestions in `ThreadSession` with backend-prevalidated SQL template metadata.
6. If the user selects a suggestion, backend runs instant suggested follow-up resolution over current evidence IDs and marks that suggestion answered.
7. If the user selects `Custom question`, backend runs the typed prompt through `Instant`, `Auto`, or `Agent`; Auto escalates to Toolhouse only when evidence coverage says the thread bundle is insufficient.
8. Backend rejects ambiguous modal submissions that include both a selected suggestion and custom text.
