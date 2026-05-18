# Local Readiness Notes

Upload this file when Toolhouse Agent Builder asks for local readiness notes.

## Current Status

The CRE Knowledge Engine backend is ready for a bounded Toolhouse worker integration.

Toolhouse should act as the deeper-analysis worker. The local backend remains the source of truth for Slack intake, queued jobs, Postgres evidence, deterministic retrieval, citation validation, and final Slack posting.

## Date And Demo Context

- Current readiness date: 2026-05-17.
- Demo reference date for availability parsing: 2026-05-17.
- Slack request mode: HTTP Events API / interactivity, not Socket Mode.
- Slack `Look deeper` behavior: backend ACKs immediately, queues work, validates the agent response, then posts to the original thread.

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

## Citation Readiness

The backend already validates Toolhouse-style responses with `validate_agent_response(...)`.

Rules:

- The worker may cite only evidence IDs returned by `explain_evidence` or another backend-validated query evidence path.
- Broad read-only tools such as `aggregate_properties`, `search_source_chunks`, and `nearby_properties` currently return supporting source/property context but do not mint new query evidence IDs.
- If those tools uncover useful context that is not in the allowed evidence set, the worker should mention it as supporting context or missing follow-up evidence, not as a cited CRE fact.
- The backend rejects unsupported citations and invalid Toolhouse output contracts before posting to Slack.

## Current Data Readiness

Latest known audit state:

- 14 source documents.
- 14 structured property records.
- 0 sources without chunks.
- 3 sources with text but no extracted property rows.
- 0 missing source URLs on property-backed records after live Slack sync.
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

Latest full-suite count: 81 tests passing.

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
