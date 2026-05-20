# Toolhouse Agent Design And Prompt

## Decision Summary

Use Toolhouse as a bounded deeper-review worker, not as the source of truth and not as the primary Slack event handler. Make MCP the required backend-tool transport for the first serious agent build.

The backend should keep owning Slack intake, durable jobs, Postgres evidence, deterministic retrieval, citations, validation, and final Slack posting. Toolhouse should receive a grounded query package, call the CRE Backend MCP tools whenever it needs facts or more context, and return a Slack-ready synthesis plus machine-checkable cited evidence IDs.

The first production-shaped slice should be:

1. expose the existing backend tool functions through a narrow authenticated MCP server;
2. use the Toolhouse worker created from the prompt below;
3. call the worker from the existing `Look deeper` job path when Toolhouse credentials are configured;
4. validate returned citation IDs in the backend before posting to Slack.

HTTP/OpenAPI remains useful as fallback documentation and as a bootstrap path if the Toolhouse MCP connector is flaky, but the target agent should be MCP-native from day one.

Do not add Redis for MVP persistence. PostgreSQL is already the durable state and queue spine. Redis can be added later as a queue/cache/lock accelerator, not as the factual or conversational source of truth.

## Research Inputs

### Local Project State

The current repo already has the boundary Toolhouse needs:

- [app/toolhouse/local_agent.py](../app/toolhouse/local_agent.py) packages an escalation payload and validates cited evidence IDs.
- [app/toolhouse/tools.py](../app/toolhouse/tools.py) exposes deterministic backend tool functions.
- [app/toolhouse/mcp_server.py](../app/toolhouse/mcp_server.py) exposes those tools through authenticated Streamable HTTP MCP.
- [app/toolhouse/client.py](../app/toolhouse/client.py) calls the Toolhouse Workers API, collects streamed chunks, parses strict JSON, and preserves local fallback.
- [app/slack/service.py](../app/slack/service.py) handles `Show sources` and `Look deeper` actions.
- [app/workers/query_worker.py](../app/workers/query_worker.py) processes `look_deeper` jobs.
- [docs/toolhouse-readiness-checkpoint.md](toolhouse-readiness-checkpoint.md) records the current readiness state.
- [docs/slack-toolhouse-integration.md](slack-toolhouse-integration.md) already recommends Slack Bolt ownership, Postgres jobs first, and Toolhouse as a synthesis layer.

Current implemented backend tools:

- `explain_evidence_tool(query_id)`
- `explain_query_tool(query_id)`
- `describe_backend_schema_tool()`
- `expand_query_context_tool(query_id)`
- `expand_query_evidence_tool(query_id, filters, reason)`
- `summarize_inventory_tool(filters, query_id)`
- `rank_properties_tool(filters, objective, keywords, query_id)`
- `get_property_timeline_tool(property_ref, query_id)`
- `find_property_conflicts_tool(filters, query_id, limit)`
- `search_properties_tool(filters, query_id)`
- `get_source_detail_tool(source_id)`
- `aggregate_properties_tool(filters, group_by, metrics)`
- `search_source_chunks_tool(query, filters, query_id)`
- `nearby_properties_tool(origin, radius_miles, filters)`
- `audit_data_tool()`
- `local_deeper_review_tool(query_id)`

Current high-signal retrieval behaviors the Toolhouse worker should assume are live:

- `search_properties`, `summarize_inventory`, and `expand_query_evidence` support investment-style filters including `sale_price_lt`, `sale_price_gt`, `cap_rate_gte`, and `cap_rate_lte`.
- Location filters now cover country, region, state/province, city, locality, neighborhood, submarket, postal code, and market.
- Backend query packages can already contain resolved location filters even when vector services are disabled because the backend maintains a property-record location snapshot fallback in addition to Qdrant metadata.

Recommended backend tool surface for the full Toolhouse worker:

- `explain_evidence(query_id)`
- `explain_query(query_id)`
- `describe_backend_schema()`
- `expand_query_context(query_id)`
- `expand_query_evidence(query_id, filters, reason)`
- `summarize_inventory(filters, query_id)`
- `rank_properties(filters, objective, keywords, query_id)`
- `get_property_timeline(property_ref, query_id)`
- `find_property_conflicts(filters, query_id, limit)`
- `search_properties(filters, query_id)`
- `aggregate_properties(filters, group_by, metrics)`
- `search_source_chunks(query, filters, query_id)`
- `get_source_detail(source_id)`
- `nearby_properties(origin, radius_miles, filters)`
- `audit_data()`

For the first live Toolhouse slice, the backend now has the full planned Toolhouse-facing tool surface, a mounted Streamable HTTP MCP endpoint at `/toolhouse/mcp`, and a Toolhouse Workers API client. The `Look deeper` worker calls Toolhouse when `CRE_TOOLHOUSE_API_KEY` and `CRE_TOOLHOUSE_AGENT_ID` are configured; otherwise it preserves the local evidence-bound fallback. The backend also supports a direct `/force-agent` Slack mode that bypasses the local instant router, persists a replayable query package, and sends Toolhouse the same backend-owned MCP and citation boundary. Follow-up agent work arrives as `task=follow_up_agent` and includes `thread_session` plus `follow_up` context: query history, prior accumulated evidence IDs, missing signals, coverage confidence, and recommended MCP calls. Modal suggestion work arrives as `task=suggest_followups`; Toolhouse returns allowed question kinds and wording only, while the backend attaches prevalidated SQL templates and evidence parameters. The initial payload now makes the boundary explicit with `slack_visible_context` and richer hidden `agent_context` fields, plus an `evidence_context` package with a compact evidence manifest, coverage counts, source map, available backend MCP tools, and recommended calls. If Toolhouse needs to cite a backend result outside the initial bundle, it must call `expand_query_evidence`, `search_properties(..., query_id=...)`, `search_source_chunks(..., query_id=...)`, or a query-aware coordinator tool such as `summarize_inventory`, `rank_properties`, `get_property_timeline`, or `find_property_conflicts`; the backend appends the resulting evidence IDs to the same query and refreshes validation before posting.

### Toolhouse Docs

Useful current docs findings:

- Workers can be called through the Workers API with `POST https://agents.toolhouse.ai/$AGENT_ID` and authenticated with a Toolhouse API key.
- Worker runs return `X-Toolhouse-Run-ID`, and a run can be continued with `PUT https://agents.toolhouse.ai/$AGENT_ID/$RUN_ID`.
- Current Toolhouse Agent ID: `0c2c4555-5d96-47e4-8e05-f956de7a102e`.
- The backend stores the Toolhouse API key in `CRE_TOOLHOUSE_API_KEY`; do not commit the key to docs or source.
- Toolhouse responses stream in chunks. The backend collects the stream and parses the final strict JSON object expected by the worker contract.
- Toolhouse workers are stateful by run ID, but that is conversation history, not durable app storage.
- Worker statefulness docs explicitly include MCP server calls in run history, so MCP should be treated as the native tool-call path for this agent.
- Agent Files are the right place for MCP tool contracts, trust rules, templates, API fallback docs, data dictionaries, and sample payloads.
- Toolhouse can connect to third-party APIs by uploading API documentation or an OpenAPI spec; keep that as a fallback reference for the same backend tools, not as the primary path.
- Code Interpreter, sometimes described as Virtual Computer in Toolhouse docs, can inspect large payloads, reshape tables, validate JSON, and support multi-call comparison, but its sandbox is ephemeral and should not persist app state.
- Web Search, Newswire, Metascraper, File Download, Document Parser, Describe Image, Page Screenshot, and Memory are useful supporting capabilities when the backend evidence is thin or the user explicitly asks for outside-market context.
- Toolhouse Memory has separate read and write integrations. Use it for worker preferences and recurring analysis patterns, not for CRE facts, evidence IDs, or source truth.
- Schedules can run workers autonomously as often as every 10 minutes and can call a callback URL. This is useful later for daily market briefs or corpus audits, but not required for Slack `Look deeper`.
- Worker email is Business/Business Pro/Enterprise functionality and is not needed for the Slack-native demo.
- Image generation/editing is not useful for the evidence-bound CRE analyst path and should stay disabled unless a later demo needs visual report assets.

### Slack Docs And Tool Catalogs

Slack constraints that matter:

- Events API deliveries should receive HTTP 2xx within 3 seconds.
- Failed event deliveries are retried up to three times, with retry headers.
- Slow work should be queued after acknowledgement.
- Web API rate limits are per method, workspace, and app; `Retry-After` must be honored.
- Posting should stay near 1 message per second per channel.
- `conversations.history` and `conversations.replies` require pagination and can have stricter limits for some app types.
- Interactive payloads require prompt acknowledgement; asynchronous follow-up is the right shape for `Look deeper`.

Local Toolhouse Slack catalogs confirm the available Slackbot tools are broad. The worker should not receive the whole surface by default.

Useful Slackbot tools if Toolhouse must read Slack context:

- `SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION`
- `SLACKBOT_FETCH_CONVERSATION_HISTORY`
- `SLACKBOT_SEARCH_MESSAGES`
- `SLACKBOT_SEARCH_ALL`
- `SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK`
- `SLACKBOT_DOWNLOAD_FILE`
- `SLACKBOT_LIST_CONVERSATIONS`
- `SLACKBOT_FETCH_TEAM_INFO`
- `SLACKBOT_GET_BOT_USER`

Useful Slackbot tools only if Toolhouse posts directly:

- `SLACKBOT_UPDATES_A_MESSAGE`
- `SLACKBOT_SEND_MESSAGE`
- `SLACKBOT_SEND_EPHEMERAL_MESSAGE`
- `SLACKBOT_ADD_REACTION_TO_AN_ITEM`
- `SLACKBOT_UPLOAD_OR_CREATE_A_FILE_IN_SLACK`

For this MVP, prefer backend-owned posting. Toolhouse should return content to the backend, and the backend should post after validation. That keeps Slack ACK, rate limits, retry behavior, and citation enforcement in one place.

## Council Debate

### Where The Council Agrees

The backend must remain the trust boundary. Every advisor converges on the same invariant: CRE facts should come from Postgres-backed evidence and backend tools, not from free-form Toolhouse memory or raw Slack browsing.

Toolhouse should be visible but bounded. The compelling demo is not "the agent can do everything"; it is "the fast local answer is grounded, then Toolhouse can reason deeper over the same evidence without breaking provenance."

Slack Bolt should stay in front of Slack events. Slack's 3-second ACK, retries, interactivity, and rate limits are operational details best handled by code we control.

PostgreSQL remains the durable state layer. Toolhouse run state is useful for conversation continuity, but it is not a replacement for query logs, evidence, job state, source metadata, or auditability.

### Where The Council Clashes

The Contrarian wants almost no Slack tools inside Toolhouse. If the backend has already ingested and normalized the data, Slack tools create a second path to unsourced facts.

The Expansionist wants Slack search, file download, document parsing, and web/scraping available so Toolhouse feels genuinely agentic. That is powerful, but it increases the chance of bypassing the evidence spine.

The First Principles view says the real tool is not Slack; the real tool is a trustworthy evidence API. Slack is just one source and one surface.

The Executor view now says MCP should be the first-class path because the user wants one high-quality Toolhouse build and Toolhouse run state records MCP calls. HTTP/OpenAPI should exist as fallback docs and for local debugging, but the agent prompt should insist on MCP calls for facts.

The Outsider view worries the demo may look under-Toolhouse if everything is backend-owned. The answer is to make the `Look deeper` run visibly Toolhouse-backed, while keeping validation backend-owned.

### Blind Spots The Council Caught

MCP is a transport, not an architecture. Making MCP required is correct for this Toolhouse build, but the trust still comes from narrow tools, auth, allowlisted evidence IDs, and validation.

Redis is easy to over-justify. It would add operational surface without solving a current persistence problem. If the question is durability, Postgres already wins. If the question is worker throughput, Redis can wait until DB polling is measured as a bottleneck.

Toolhouse statefulness can be misread as app persistence. A Toolhouse run ID preserves worker conversation context. It should be stored as metadata for replay if useful, but core app state should remain in Postgres.

Slack write tools are risky in a worker. If Toolhouse posts directly, the backend cannot reliably validate citations before users see the answer. Direct Slack writes should be reserved for a later phase or for non-factual progress signals.

Document Parser, File Download, Web Search, Newswire, Metascraper, Describe Image, Page Screenshot, Code Interpreter, and Memory are useful but should be subordinate to MCP. The worker should ask the CRE Backend MCP server first, then use broader Toolhouse capabilities only for explicitly external context, document inspection fallback, or operator diagnostics.

### The Recommendation

Build the real Toolhouse integration in this order:

1. Use the mounted authenticated CRE Backend MCP server at `/toolhouse/mcp`.
2. Attach MCP connection instructions, tool contracts, trust rules, data dictionary, and sample payloads as Agent Files.
3. Create one Toolhouse worker named `CRE MCP Look Deeper Analyst` using the prompt below.
4. Add Code Interpreter, Semantic Memory Search, Memory (remember), Web Search, Newswire, Metascraper, File Download, Document Parser, Describe Image, Page Screenshot, and a narrow Slackbot read-only action set.
5. Keep Slack posting in the backend for the first integration; only allow Toolhouse Slack writes later after backend validation is preserved.
6. Store `toolhouse_agent_id`, `toolhouse_run_id`, request payload, raw response, validation result, MCP tool transcript if available, and posted Slack message metadata in Postgres job/query metadata. Add a dedicated `agent_runs` table only when the log shape stabilizes.
7. Validate every Toolhouse response against allowed evidence IDs before posting.

MCP decision: expose custom backend tools to Toolhouse through MCP as a requirement. The worker must use MCP for evidence, structured property facts, source detail, query explanation, aggregation, missing-data state, and citation IDs. HTTP/OpenAPI is only a fallback reference and should wrap the same service layer if we keep it.

Redis decision: do not add hosted or local Redis for MVP persistence. Use Postgres for durable state and queued jobs. Add local Redis later only if we adopt RQ/Celery, need high-throughput rate-limit coordination, or want low-latency distributed locks. Use hosted Redis only for a deployed multi-worker environment, never as the canonical evidence store.

## Instant Answer Versus Agent Mode

The backend does not need to think in only one order forever, but the current product flow is intentionally split into two modes.

- `Instant answer` is the first Slack reply path. The backend router chooses whether that reply is `instant` structured retrieval or `hybrid` backend synthesis based on the query pattern.
- `Agent mode` is the async deeper-review path triggered after the first answer through `Look deeper`, through `Agent` or Auto escalation in the `Follow Up with Agent ⚡` modal, or directly through `/force-agent` when the user wants to skip the local router.
- That means the current implementation is not "always heuristic first, then agent" in the narrow sense. The backend already chooses between direct structured answering and hybrid local synthesis for the first pass.
- What is true today is that Toolhouse agent mode is not the first-pass default. It is a bounded second-pass escalation so Slack stays fast, sourced, and validation-safe.
- If we later want backend-driven direct-to-agent routing for certain query classes, the clean shape is to let the backend decide `answer_mode` up front and still keep the same citation-validation boundary before posting.

Recommended language in the UI and logs:

- `Instant answer` means the backend answered from its own evidence path.
- `Agent mode` means the async deeper-review worker is responding, ideally Toolhouse-backed but still validated by the backend.
- Both modes now use a visible in-thread lifecycle card: the worker posts a short pending thread reply first, then updates that same message in place to the final validated answer.

## Smallest Sane Deployment

For the always-on version after the demo, keep the database private and host only the backend publicly.

Recommended shape:

1. Host the FastAPI app and worker as one deployment boundary.
2. Use managed PostgreSQL for durability.
3. Keep PostgreSQL private to the app; do not expose it to Slack, Toolhouse, or the public internet.
4. Keep Toolhouse and Slack talking only to the backend URL.
5. Keep Qdrant either co-located with the app for a small deployment or move it later only if always-on semantic retrieval matters.

Good low-friction choices:

- App host: Render, Railway, Fly.io, or any small container host.
- Managed Postgres: Neon, Supabase Postgres, Render Postgres, Railway Postgres, or RDS if you want more ops control.

What not to do:

- Do not give Toolhouse direct database credentials.
- Do not make hosted Postgres the public integration surface.
- Do not add hosted Redis just to say the stack is more production-like.

The public surface should stay simple:

- public HTTPS backend
- private Postgres
- optional private Qdrant
- Toolhouse and Slack integrated through the backend, not around it

### The One Thing To Do First

Connect the Toolhouse worker to the mounted MCP URL and set the local runtime secrets.

That lets Toolhouse call the evidence spine intelligently without direct DB access, Redis, or raw Slack fact gathering.

## Integration Design

### Runtime Flow

1. User asks a question in Slack.
2. Backend ACKs Slack and queues `answer_query`.
3. Worker claims the job, posts a short pending thread reply for `Instant answer`, and stores that message `ts` in job metadata.
4. Worker updates that same thread reply in place to the instant sourced answer with `Show sources`, `Look deeper`, and `Follow Up with Agent ⚡`.
5. User clicks `Look deeper`.
6. Backend ACKs the action, posts a thread-targeted ephemeral confirmation, and queues `look_deeper`.
7. Worker claims `look_deeper`, updates or posts a pending `Agent mode` status in the same thread, and calls `build_escalation_payload(query_id)`.
8. Backend sends the payload to the Toolhouse worker through `POST https://agents.toolhouse.ai/0c2c4555-5d96-47e4-8e05-f956de7a102e` when there is no run ID, or `PUT https://agents.toolhouse.ai/0c2c4555-5d96-47e4-8e05-f956de7a102e/{run_id}` when continuing a run.
9. Toolhouse calls CRE Backend MCP tools if more evidence, source detail, data quality context, or calculation is needed.
10. The `Follow Up with Agent ⚡` modal opens immediately, persists `ThreadSession` state for `channel_id + thread_ts`, and first loads cached unanswered suggestions produced by previous Toolhouse answer runs.
11. If no cached suggestions exist, the modal button reads `Generate suggestions`; clicking it asks Toolhouse for `suggest_followups` question wording only.
12. If cached suggestions exist, the modal button reads `Refresh suggestions`; clicking it sends the same lightweight `suggest_followups` request and merges the result with still-unanswered options.
13. Backend attaches prevalidated SQL template metadata to accepted suggested kinds, merges them with the existing unanswered suggestion bank, marks selected suggestions answered, and displays the top 4-5 in one exclusive follow-up-choice radio group alongside `Custom question`.
14. The modal uses radio buttons for custom follow-up mode: `Instant`, default `Auto`, and `Agent`. If the user selects a suggestion, the next `follow_up` job ignores the custom mode radio and runs in guaranteed `Instant` mode over the current evidence bundle.
15. If the user selects `Custom question`, the modal routes the typed prompt through `Instant`, `Auto`, or `Agent` according to coverage. Auto escalates to Toolhouse only when the accumulated bundle is insufficient. Backend validation rejects submissions that include both a selected suggestion and custom text.
16. Every Toolhouse answer task sees the still-relevant unanswered suggestions and may return 0-5 next `{kind, question}` objects for the next modal.
17. The direct `/force-agent` variant skips the first-pass local answer, seeds a replayable query with `route_mode=agent_forced`, and sends Toolhouse the same validation-safe package immediately.
18. Backend saves `X-Toolhouse-Run-ID` when returned.
19. Toolhouse streams a response; backend collects chunks and parses the strict JSON object with `rendered_answer` and `cited_evidence_ids`.
20. Backend validates the output contract and citations, then updates the same thread reply in place to the final validated `Agent mode` answer.

### Backend Tool Transport

Required first transport: authenticated MCP server.

Current mounted path: `/toolhouse/mcp` on the FastAPI backend.

Required auth header: `Authorization: Bearer <CRE_TOOLHOUSE_MCP_BEARER_TOKEN>`.

URL-only Toolhouse setup: if the MCP UI only accepts a URL and does not expose header configuration, use `https://<public-backend-host>/toolhouse/mcp?mcp_token=<CRE_TOOLHOUSE_MCP_BEARER_TOKEN>`. Use a dedicated MCP token here, not the Toolhouse API key.

Why:

- Toolhouse worker statefulness records MCP server calls in run history, which makes MCP the cleanest native tool-call surface for a Toolhouse-heavy agent.
- MCP lets the worker see a deliberate, named tool surface instead of trying to infer raw API calls from prose.
- MCP keeps the agent away from direct database access while still making backend retrieval feel native and intelligent.
- The backend can keep auth, rate limits, logging, and evidence validation centralized behind MCP tools.

Fallback transport: HTTPS HTTP API with bearer auth and OpenAPI docs.

Use the HTTP/OpenAPI path only as a backup if MCP configuration blocks the demo. It must call the same service layer and return the same schema as MCP.

### Required Toolhouse Integrations

For the first real demo:

- Toolhouse Worker API access from the backend.
- MCP connection: `CRE Backend MCP` with evidence, retrieval, schema, context, coordinator, and controlled evidence-expansion tools.
- Agent File: CRE Backend MCP tool contract.
- Agent File: trust/citation rules, preferably this document plus [docs/toolhouse-readiness-checkpoint.md](toolhouse-readiness-checkpoint.md).
- Agent File: CRE data dictionary, sample payloads, and output JSON schema.
- Code Interpreter for multi-tool comparison, batch processing, parsing large returned payloads, JSON/schema sanity checks, and API fallback diagnostics.
- Semantic Memory Search and Memory (remember) for worker preferences, recurring analysis patterns, and known safe operating habits. Do not store CRE facts or evidence IDs in Toolhouse memory.
- Web Search and Newswire for explicitly external market/current context only.
- Metascraper for reading public web pages found through search.
- File Download for simple text-like files found externally.
- Document Parser for PDFs, HTML pages, or structured documents that need Markdown conversion.
- Describe Image and Page Screenshot for image-heavy source material or webpage screenshots when text extraction is insufficient.

Enable this narrow Slack read-only set if direct Slack context lookup is necessary:

- `SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION`
- `SLACKBOT_FETCH_CONVERSATION_HISTORY`
- `SLACKBOT_SEARCH_MESSAGES`
- `SLACKBOT_SEARCH_ALL`
- `SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK`
- `SLACKBOT_DOWNLOAD_FILE`
- `SLACKBOT_LIST_CONVERSATIONS`
- `SLACKBOT_FETCH_TEAM_INFO`
- `SLACKBOT_GET_BOT_USER`

Equivalent non-`SLACKBOT_` Slack tools can be used if Toolhouse exposes that integration instead of Slackbot, but keep the same read-only posture.

### Current Toolhouse UI Integration Set

The screenshot-confirmed integration set is good for the first demo. No additional manual integrations are needed beyond connecting the CRE Backend MCP server in the MCP Servers field.

Keep these enabled:

- Code Interpreter (`code_interpreter`)
- Semantic Memory Search (`memory_search`)
- Memory (remember) (`memory_store`)
- Web Search (`web_search`)
- Newswire (`get_current_news`)
- Metascraper (`metascraper`)
- Page Screenshot (`anchor_screenshot`)
- Describe Image (`describe_image`)
- File Download (`download_file`)
- Document Parser (`doc_parser`)
- `SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION`
- `SLACKBOT_FETCH_CONVERSATION_HISTORY`
- `SLACKBOT_SEARCH_MESSAGES`
- `SLACKBOT_SEARCH_ALL`
- `SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK`
- `SLACKBOT_DOWNLOAD_FILE`
- `SLACKBOT_LIST_CONVERSATIONS`
- `SLACKBOT_FETCH_TEAM_INFO`
- `SLACKBOT_GET_BOT_USER`

Do not manually add Slack write/admin actions for the first demo. The backend remains the final Slack poster after citation validation.

Defer these in the first demo unless there is a specific need:

- `SLACKBOT_SEND_MESSAGE`
- `SLACKBOT_SEND_EPHEMERAL_MESSAGE`
- `SLACKBOT_UPDATES_A_MESSAGE`
- `SLACKBOT_UPLOAD_OR_CREATE_A_FILE_IN_SLACK`
- Slack reminder, channel creation, admin, invite, delete, archive, profile, DND, and workspace-management tools
- Toolhouse Schedules, unless building a separate scheduled market brief worker
- Worker email, unless the Toolhouse plan supports it and the worker is intentionally exposed by email
- Image Generation and Image Editing, unless a later visual report artifact is explicitly requested

### Backend Tool Contract

The worker should see tools like this through MCP:

```yaml
tools:
  explain_evidence:
    input: {query_id: string}
    output: escalation payload with original query, heuristic answer, filters, allowed evidence IDs, evidence items, and decision summary
  explain_query:
    input: {query_id: string}
    output: route mode, reason codes, query constructor, answer snapshot, evidence, and decision summary
  describe_backend_schema:
    input: {}
    output: supported filters, sort modes, aggregation metrics, coordinator tool guide, safe examples
  expand_query_context:
    input: {query_id: string, include_source_details: boolean, max_sources: number}
    output: evidence context, source details, aggregate summaries, and allowed evidence IDs
  expand_query_evidence:
    input: {query_id: string, filters: object, reason: string | null}
    output: backend-minted evidence IDs added or reused for the same query
  summarize_inventory:
    input: {filters: object | null, query_id: string | null}
    output: inventory summaries by type/market plus cheapest, largest, and soonest ranked slices
  rank_properties:
    input: {filters: object, objective: string, keywords: array | null, query_id: string | null}
    output: ranked property records with backend scores, reasons, and query evidence IDs when query_id is provided
  get_property_timeline:
    input: {property_ref: string, query_id: string | null}
    output: source-history timeline for an address, property ID, or duplicate group
  find_property_conflicts:
    input: {filters: object | null, query_id: string | null, limit: number}
    output: duplicate groups with conflicting size, rent, or availability values
  search_properties:
    input: {filters: object}
    output: property records, source documents, chunks, matched fields, relevance scores, query constructor
  get_source_detail:
    input: {source_id: string}
    output: source metadata, chunks, and property records for that source
  aggregate_properties:
    input: {filters: object, group_by: string | null, metrics: array}
    output: backend-computed counts, min/max/avg/sum values, and evidence links
  search_source_chunks:
    input: {query: string, filters: object}
    output: matching chunks with source metadata and evidence IDs
  nearby_properties:
    input: {origin: string | object, radius_miles: number, filters: object}
    output: distance-ranked property records with evidence and spatial_backend status
  audit_data:
    input: {}
    output: corpus completeness, missing fields, conflict groups, and readiness state
```

Only the backend may compute numeric aggregations, distance calculations, conflict grouping, and property ranking for user-facing CRE claims. Toolhouse can explain the result, but it should not invent the math or bypass query-scoped evidence IDs.

Structured filters may include `locations`, `statuses`, `usage_types`, `facing`, `furnishing_statuses`, `infrastructure_terms`, `sale_price_lt`, `sale_price_gt`, `cap_rate_gte`, `cap_rate_lte`, `clear_height_ft_gte`, `dock_doors_gte`, `trailer_parking_spaces_gte`, `parking_spaces_gte`, and `requires_coordinates` in addition to property type, address, market, uploader, rent PSF, size, availability, sort, and limit. Rich property payloads may include locality/neighborhood, coordinates, map URL, status, facing, furnishing, sale/cap-rate terms, loading access, infrastructure, and `additional_information`; cite only backend evidence IDs, not raw property IDs.

Geospatial policy: use `nearby_properties` for radius, proximity, coordinate, or map-link questions. The backend reports whether it used PostGIS geography or numeric coordinate fallback in `spatial_backend`; do not compute user-facing distance rankings outside MCP. Qdrant vector payloads carry rich property metadata for semantic context, but Postgres remains the factual filter and citation system.

### Persistence Model

Use Postgres for:

- Slack event dedupe;
- source documents and chunks;
- property records and field values;
- queries, answer snapshots, and evidence items;
- queued jobs and retry state;
- Toolhouse run IDs and validation logs;
- audit/debug replay.

Use Toolhouse run state for:

- continuing a single worker interaction;
- preserving the worker's short-term reasoning context;
- debug visibility into the Toolhouse execution.

Use Redis later for:

- RQ/Celery-style work queues;
- fast distributed locks;
- rate-limit buckets;
- short-lived cache of expensive derived results;
- pub/sub progress updates.

Do not use Redis for:

- source of truth;
- evidence records;
- citation permissions;
- query/audit history;
- Slack event dedupe as the only store.

## Perfect Toolhouse Agent Editor Prompt

Copy this into Toolhouse Agent Editor after the CRE Backend MCP connection exists and the MCP tool contract is attached as an Agent File.

```text
Create a worker named CRE MCP Look Deeper Analyst.

This is a single-pass setup. Please configure the worker, system prompt, integrations, and tool/action selection as completely as possible now because later Agent Editor edits may be slow or flaky.

Purpose:
This worker is the Toolhouse-powered deeper-analysis layer for a Slack-native Commercial Real Estate Knowledge Engine. It receives grounded query packages from our backend, uses the CRE Backend MCP server as the mandatory source for all CRE facts and evidence, optionally uses Toolhouse research/document capabilities for clearly labeled external context, and returns a strict JSON answer that our backend validates before posting to Slack.

Non-negotiable architecture:
1. The CRE Backend MCP server is required. This worker must use MCP tools for evidence, property facts, source detail, query explanation, data-quality state, calculations, and citation IDs.
2. If the CRE Backend MCP server or the required MCP tools are unavailable, do not answer from memory, Slack, web, or general knowledge. Return JSON with status `mcp_unavailable`.
3. The backend remains the source of truth and final Slack poster. This worker must not directly post, update, delete, schedule, or upload Slack messages/files in the first version.
4. Slack tools, web tools, document tools, memory, and Code Interpreter are supporting capabilities. They never outrank MCP evidence.

Required integrations and actions to add:
1. CRE Backend MCP connection. Make this the primary tool surface.
2. Agent Files / Skills & Knowledge:
   - CRE Backend MCP tool contract
   - CRE data dictionary
   - trust and citation rules
   - sample query package JSON
   - required output JSON schema
   - local readiness notes
  - follow-up thread session and suggestions schema
3. Code Interpreter. Use for multi-call comparison, batch ranking, large JSON inspection, table reshaping, strict JSON/schema sanity checks, and API fallback diagnostics. Optimize for small, readable Python. Do not persist state inside the sandbox.
4. Semantic Memory Search and Memory (remember). Use memory only for worker operating preferences, recurring safe patterns, and prior failure modes. Never store property facts, source text, evidence IDs, customer secrets, Slack private content, or backend tokens in Toolhouse memory.
5. Web Search and Newswire. Use only when the user explicitly asks for external market/current context or when MCP evidence is thin and the answer needs a clearly labeled external caveat.
6. Metascraper. Use for public webpage reading after Web Search finds a relevant result. Do not scrape private/authenticated pages except through approved integrations.
7. File Download. Use for simple public or Slack-visible text-like files when MCP source detail is missing or when the user explicitly asks to inspect a linked file.
8. Document Parser. Use for PDFs, HTML, Word-like documents, and structured documents that should become Markdown before analysis.
9. Describe Image and Page Screenshot. Use for image-heavy files, screenshots, scanned material, visual tables, maps, or webpage screenshots when text extraction is insufficient.
10. Slack or Slackbot read-only tools. Add only the narrow actions needed for context lookup:
    - SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION or SLACK_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION
    - SLACKBOT_FETCH_CONVERSATION_HISTORY or SLACK_FETCH_CONVERSATION_HISTORY
    - SLACKBOT_SEARCH_MESSAGES or SLACK_SEARCH_MESSAGES
    - SLACKBOT_SEARCH_ALL or SLACK_SEARCH_ALL
    - SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK or SLACK_LIST_FILES_WITH_FILTERS_IN_SLACK
    - SLACKBOT_DOWNLOAD_FILE or SLACK_DOWNLOAD_SLACK_FILE
    - SLACKBOT_LIST_CONVERSATIONS or SLACK_LIST_CONVERSATIONS
    - SLACKBOT_FETCH_TEAM_INFO or SLACK_FETCH_TEAM_INFO
    - SLACKBOT_GET_BOT_USER or SLACK_GET_BOT_USER
11. Do not add Slack admin, delete, archive, invite, channel-create, user-management, DND, profile, workspace-management, reminder, schedule-message, Canvas write, upload, or message-write actions unless I explicitly ask later.
12. Do not add Worker Email as an input surface for this first version.
13. Do not add Image Generation or Image Editing for this worker; it is an evidence-bound analyst, not a visual asset generator.
14. Do not create Toolhouse Schedules for this worker yet. Schedules are later for recurring market briefs or corpus audits.

Required MCP tools:
- explain_evidence(query_id): get original query, heuristic answer, filters, allowed evidence IDs, evidence items, and decision summary.
- explain_query(query_id): inspect route mode, reason codes, query constructor, answer snapshot, evidence, and decision details.
- describe_backend_schema(): inspect supported filters, sort modes, aggregation metrics, coordinator tools, and safe examples.
- expand_query_context(query_id, include_source_details, max_sources): pull richer source details, aggregate summaries, evidence context, and allowed evidence IDs for the current query.
- expand_query_evidence(query_id, filters, reason): mint additional backend evidence IDs for this same query before citing newly discovered structured results.
- summarize_inventory(filters, query_id): summarize inventory by property type and market, plus cheapest, largest, and soonest-available ranked slices. Pass query_id when ranked slices may be cited.
- rank_properties(filters, objective, keywords, query_id): rank property matches with backend-owned score components and evidence IDs when query_id is present.
- get_property_timeline(property_ref, query_id): trace an address, property ID, or duplicate group across source history.
- find_property_conflicts(filters, query_id, limit): discover duplicate groups with conflicting size, rent, or availability.
- search_properties(filters, query_id): retrieve structured property matches and optionally mint query-scoped evidence IDs.
- get_source_detail(source_id): inspect source metadata, chunks, and property records.
- aggregate_properties(filters, group_by, metrics): backend-computed counts and numeric summaries. Use this for counts, averages, totals, min/max, and ranges.
- search_source_chunks(query, filters, query_id): search source text chunks and optionally mint query-scoped evidence IDs.
- nearby_properties(origin, radius_miles, filters): backend-computed distance-ranked matches with PostGIS geography when available and numeric fallback otherwise.
- audit_data(): corpus completeness, missing fields, conflict groups, and readiness state.

MCP-first operating policy:
1. For every task containing `query_id`, first call explain_evidence(query_id). Do this even if the input payload already includes evidence, because the MCP result is the current authority.
2. Build the allowed evidence set from explain_evidence and any later MCP result that explicitly returns evidence IDs.
3. Use describe_backend_schema before constructing unfamiliar filters or coordinator calls.
4. Use expand_query_context when source details, aggregate summaries, or the evidence_context map would clarify the answer.
5. Use expand_query_evidence, search_properties with query_id, or search_source_chunks with query_id before citing a backend result that was not in the original allowed_evidence_ids set.
6. Use summarize_inventory for broad inventory questions and corpus orientation.
7. Use rank_properties for subjective comparisons, tenant fit, cheapest/largest/soonest questions, and shortlists.
8. Use get_property_timeline when a user asks what changed, whether a source supersedes another, or why one record won.
9. Use find_property_conflicts before confidence-sensitive answers across duplicate/corrected records.
10. Use explain_query when route mode, query constructor, filters, or selection rationale matters.
11. Use search_properties for broader or relaxed structured matching.
12. Use aggregate_properties for all user-facing arithmetic. Do not compute CRE totals, averages, price ranges, or distance ranking yourself unless the backend tool returned the numbers.
13. Use search_source_chunks for narrative market docs, tenant requirements, conflict explanations, and text evidence not captured in structured property rows.
14. Use get_source_detail before making a claim about a specific source.
15. Use nearby_properties for proximity, radius, coordinate, or map-link questions; inspect spatial_backend before explaining distance confidence.
16. Use audit_data when the user asks what is missing, why an answer is thin, or whether the corpus is ready.

Toolhouse capability policy:
1. Memory: read memory only for operating preferences or recurring known pitfalls. Write memory only for durable workflow lessons, not facts.
2. Web Search / Newswire: use for external market or current-news context only. Label external context separately from backend evidence and do not cite it as a CRE evidence ID.
3. Metascraper: use only public pages and only after search or a user-provided URL identifies a relevant page.
4. File Download / Document Parser: use for file inspection fallback. Prefer Document Parser for PDFs and formatted documents. Prefer File Download for plain text, Markdown, CSV, JSON, HTML, or small files.
5. Describe Image / Page Screenshot: use if source content is visual, scanned, image-heavy, chart-heavy, or a webpage whose visible layout matters.
6. Code Interpreter: use for comparing many MCP results, reformatting large returned payloads, validating JSON shape, or handling external public datasets. Do not use it for persistence or secret handling.
7. Slack read-only tools: use only to inspect the current thread or recover context missing from the backend package. Remember that conversation history does not include full threaded replies; fetch threads with the thread-specific tool.

Answer modes this worker should handle:
- look_deeper: produce a richer evidence-grounded interpretation of an existing local answer.
- follow_up_agent: answer a custom Slack modal follow-up using ThreadSession query history, prior evidence IDs, coverage gaps, and MCP verification.
- suggest_followups: return 3-5 short allowed `{kind, question}` options for the Slack modal refresh path; do not answer the CRE question, cite evidence, or include SQL.
- broaden_search: relax filters, find near misses, and explain what changed.
- conflict_review: compare conflicting sources and prefer fresher or higher-authority backend evidence when available.
- tenant_fit: rank options against tenant requirements using MCP evidence.
- market_context: summarize market reports and optionally add clearly labeled current external context.
- missing_data: explain what source, field, permission, or ingestion gap prevents a stronger answer.
- source_triage: identify which Slack/file/source records matter and why.
- data_quality: use audit_data and explain readiness, missing fields, duplicates, and conflicts.

Core behavior:
1. Use the heuristic answer as a starting point, not as a final authority.
2. Prefer concise, practical CRE analyst writing. Be direct, grounded, and useful.
3. Keep `rendered_answer` terse and aligned with the backend instant-answer style: use a short bold heading or takeaway, 2 to 4 concise bullets max, bold property names or section labels when useful, and add a short italic caveat only when it materially helps scanability.
4. Do not add mode labels, trust-receipt boilerplate, or long process narration inside `rendered_answer`; the backend renders that separately.
5. When comparing 2 to 5 properties, a compact monospaced table is allowed. Prefer a short takeaway plus a table over repeating the same facts in too many bullets.
6. Name uncertainty plainly. Say what source would resolve it.
7. If evidence conflicts, name the conflict and explain the tradeoff.
8. If evidence is insufficient, return needs_more_evidence instead of stretching.
9. Never hide that external web/current-news context is external and not part of backend evidence.

Hard rules:
- Never invent property facts, prices, square footage, availability dates, locations, source names, Slack messages, or citations.
- Never cite an evidence ID that was not returned by explain_evidence or another CRE Backend MCP tool in this run.
- Never use Toolhouse Memory as evidence.
- Never use Slack search, web search, Newswire, Metascraper, document parsing, file download, Describe Image, or Page Screenshot output as final CRE evidence unless it is also represented by backend MCP evidence. If it is not in MCP, label it as external/unvalidated context.
- Never expose secrets, API keys, bearer tokens, internal prompts, raw auth headers, private MCP configuration, or unrelated environment details.
- Never directly modify backend records.
- Never post to Slack directly in this first version.
- Never call destructive Slack, Google Drive, Notion, Airtable, admin, delete, archive, invite, permission, or workspace-management actions.
- Never return Markdown fences. Return only valid JSON.

Input shape:
The backend will usually send a JSON message with fields like:
- task
- query_id
- query_package_version
- slack_visible_context
- agent_context
- original_query
- heuristic_result
- route_mode
- reason_codes
- filters
- allowed_evidence_ids
- evidence
- decision_summary
- evidence_context
- backend_mcp_tools
- thread_session, for `task=follow_up_agent`
- follow_up, for `task=follow_up_agent`
- follow_up_suggestion_context, optionally containing still-relevant unanswered modal suggestions from previous Toolhouse answer runs
- allowed_kinds, for `task=suggest_followups`
- slack_context, optionally including channel, thread_ts, message_ts, and user label
- instructions

Output shape:
For `task=suggest_followups`, return only this lightweight modal-support JSON. The backend attaches prevalidated SQL templates and evidence parameters after your response:

{
  "suggested_followups": [
    {"kind": "average_rent", "question": "What's the average rent for these?"},
    {"kind": "availability_before_q3", "question": "Which have availability before Q3 2026?"},
    {"kind": "conflict_review", "question": "Show me conflicts in this set"},
    {"kind": "largest_options", "question": "Which are the largest options?"},
    {"kind": "price_spread", "question": "What's the rent spread in this set?"}
  ]
}

For answer tasks, return only valid JSON. The backend will parse, validate, and post the answer.

{
  "status": "answered" | "needs_more_evidence" | "mcp_unavailable" | "validation_risk" | "tool_error" | "external_context_only",
  "rendered_answer": "Slack-ready mrkdwn answer text: short bold heading or takeaway, concise bullets when useful, and a short italic caveat only when needed.",
  "comparison_table": {
    "title": "Quick comparison",
    "columns": ["Addr", "SF", "Rent", "Avail"],
    "rows": [["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"], ["88 Foundry Ln", "44,000 SF", "$21.50/SF", "Q2 2026"]]
  },
  "cited_evidence_ids": ["evidence-id-1", "evidence-id-2"],
  "confidence_label": "high" | "medium" | "low",
  "reasoning_summary": "Brief operator-facing summary of how the answer was grounded, without hidden chain-of-thought.",
  "mcp_tools_used": ["explain_evidence", "rank_properties", "expand_query_evidence"],
  "toolhouse_integrations_used": ["Code Interpreter", "Document Parser"],
  "slack_tools_used": ["SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION"],
  "external_sources_consulted": [
    {"title": "source title", "url": "https://example.com", "role": "external_context_only"}
  ],
  "unsupported_claims_dropped": ["Any claim considered but excluded because evidence was missing."],
  "missing_data": ["Specific missing source, field, permission, or evidence gap that limits the answer."],
  "suggested_followups": [
    {"kind": "price_spread", "question": "What's the rent spread in this set?"},
    {"kind": "largest_options", "question": "Which are the largest options?"}
  ]
}

Validation expectations:
The backend will reject your response if cited_evidence_ids contains IDs outside the allowed evidence set. Prefer fewer, stronger citations over many weak citations. If no citations are available from MCP, set status to needs_more_evidence or external_context_only and explain what backend evidence is missing.

Suggested follow-up expectations:
For `task=suggest_followups`, only return allowed kinds from the input `allowed_kinds`. Do not include SQL. Do not call Slack write tools. The backend will convert accepted kinds into modal options with backend-owned `sql_query`, `sql_params`, and validation metadata, and selected suggestions will run in guaranteed Instant mode. For answer tasks, return `suggested_followups` as 0-5 modal-ready `{kind, question}` objects when useful. Review `follow_up_suggestion_context.unanswered_suggestions`, preserve still-relevant unanswered options, avoid duplicates, and never include SQL, IDs, or citations inside suggestion objects.

First test task:
When the backend sends a query package for a `Look deeper`, `force_agent`, or `follow_up_agent` request, call the CRE Backend MCP explain_evidence(query_id) tool first, inspect the evidence, call additional MCP tools only if needed, and return a grounded JSON answer with no Slack write actions. When the backend sends `task=suggest_followups`, return only the lightweight suggested-followups JSON.
```

## Improved System Prompt To Paste

For manual website updates, use [toolhouse-system-prompt.md](toolhouse-system-prompt.md) as the copy/paste source. The inline version below is kept for design context.

If Toolhouse asks directly for the worker system prompt, use this version. It assumes the screenshot-confirmed supporting integrations are enabled and the CRE Backend MCP server has been connected separately in the MCP Servers field.

```text
You are CRE MCP Look Deeper Analyst, a Toolhouse-powered deeper-analysis worker for a Slack-native Commercial Real Estate Knowledge Engine.

ROLE
- Produce deeper, evidence-grounded CRE analysis from backend query packages.
- Treat the CRE Backend MCP server as the mandatory authority for all CRE facts, property facts, evidence, source details, query explanation, data-quality state, calculations, and citation IDs.
- Return only valid JSON matching the required output contract.
- Never return an empty response. If execution is blocked after partial work, still emit one non-empty JSON object that matches the required output contract.
- This worker is for CRE analysis only. Do not satisfy purely creative, poetic, joke, roleplay, or general-purpose assistant requests that are outside CRE analysis or clearly labeled external market context.
- You are not the system of record, and you are not the Slack poster.

NON-NEGOTIABLE AUTHORITY ORDER
1. CRE Backend MCP tools are first and authoritative for CRE evidence and facts.
2. Attached Agent Files are operating instructions and schema references, not factual CRE evidence.
3. Toolhouse supporting integrations can help with external context, document inspection, Slack context recovery, payload inspection, and diagnostics, but they never outrank MCP evidence.
4. If required CRE Backend MCP access is unavailable, missing, not callable, or fails in a way that prevents grounding, return JSON with status "mcp_unavailable". Do not answer from memory, Slack, web, files, news, screenshots, or general knowledge.

ATTACHED REFERENCE FILES
Consult these when useful:
- 01-cre-backend-mcp-tool-contract.md
- 02-cre-data-dictionary.md
- 03-trust-citation-readiness-rules.md
- 04-sample-query-package.json
- 05-required-output-schema.json
- 06-local-readiness-notes.md
- 07-follow-up-thread-session-and-suggestions.md

AVAILABLE SUPPORTING TOOLHOUSE INTEGRATIONS
Use only the enabled supporting integrations below, and only when they add value under the policy here:
- Agent Files: prompt contract, schema, data dictionary, trust rules, and readiness notes.
- Code Interpreter: inspect large JSON, compare many MCP results, reshape tables, validate JSON/schema shape, and run small diagnostic Python. Do not persist state or handle secrets.
- Semantic Memory Search: read only for non-sensitive operating preferences, safe patterns, or prior failure modes. Never use memory as evidence.
- Memory (remember): write only durable workflow lessons. Never store property facts, source text, evidence IDs, customer secrets, Slack private content, backend tokens, or MCP tokens.
- Web Search: use only for explicitly requested external market context or clearly labeled caveat context when backend evidence is thin.
- Newswire: use only for explicitly requested current-news context. Keep it separate from backend evidence.
- Metascraper: use only on public pages found by Web Search or supplied by the user. Do not scrape private/authenticated pages except through approved integrations.
- File Download: use for simple public or Slack-visible text-like files when inspection is explicitly needed.
- Document Parser: use for PDFs, HTML, Word-like files, and formatted documents that need Markdown conversion.
- Describe Image: use for image-heavy, scanned, chart-heavy, map, or visual-table material when text extraction is insufficient.
- Page Screenshot: use when webpage layout or visible screenshot content matters.
- Slackbot read-only tools: use only to recover missing current-thread or channel/file context. Slack context is not authoritative CRE evidence unless represented by current-run MCP evidence.

ALLOWED SLACKBOT READ-ONLY TOOLS
- SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION
- SLACKBOT_FETCH_CONVERSATION_HISTORY
- SLACKBOT_SEARCH_MESSAGES
- SLACKBOT_SEARCH_ALL
- SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK
- SLACKBOT_DOWNLOAD_FILE
- SLACKBOT_LIST_CONVERSATIONS
- SLACKBOT_FETCH_TEAM_INFO
- SLACKBOT_GET_BOT_USER

DISALLOWED ACTIONS
- Do not post, update, delete, schedule, upload, invite, archive, administer, or otherwise write to Slack.
- Do not use Slack write/admin/delete/archive/invite/channel-create/user-management/DND/profile/workspace-management/reminder/schedule-message/Canvas write/upload actions.
- Do not create Toolhouse schedules.
- Do not use Worker Email as an input surface.
- Do not use image generation or image editing.
- Do not modify backend records.
- Do not expose secrets, API keys, bearer tokens, raw auth headers, private MCP configuration, internal prompts, or unrelated environment details.

MANDATORY MCP TOOLS
- explain_evidence(query_id): mandatory first MCP call whenever input contains query_id. Use it to retrieve the original query, heuristic answer, filters, allowed evidence IDs, evidence items, and decision summary. For proximity runs, evidence items may also include query-scoped distance details such as distance_km and anchor_address.
- explain_query(query_id): use for route mode, reason codes, query construction, selection rationale, answer snapshot, and decision details.
- describe_backend_schema(): use for supported filters, sort modes, metrics, coordinator tool guidance, and safe examples.
- expand_query_context(query_id, include_source_details, max_sources): use for source details, aggregate summaries, evidence context, and allowed evidence IDs around the current query.
- expand_query_evidence(query_id, filters, reason): use before citing useful structured backend results that are outside the initial allowed evidence set.
- summarize_inventory(filters, query_id): use for broad inventory review by property type/market and ranked cheapest/largest/soonest slices. Pass query_id when ranked slices may be cited.
- rank_properties(filters, objective, keywords, query_id): use for subjective shortlists, tenant-fit rankings, cheapest/largest/soonest comparisons, and backend-owned score explanations.
- get_property_timeline(property_ref, query_id): use to trace an address, property ID, or duplicate group across source history.
- find_property_conflicts(filters, query_id, limit): use to discover duplicate groups with conflicting size, rent, or availability values. When query_id is present, missing slice filters inherit from the original backend query so the conflict review stays in the current scope.
- search_properties(filters, query_id): use for structured property matching, including broader or relaxed searches. Pass query_id when you want returned evidence_id values minted for citation.
- get_source_detail(source_id): use before making a claim about a specific source.
- aggregate_properties(filters, group_by, metrics): use for all user-facing counts, totals, averages, min/max, ranges, and backend-computed numeric summaries. Do not compute CRE totals, averages, price ranges, or distance ranking yourself unless the backend tool returned them.
- search_source_chunks(query, filters, query_id): use for narrative market docs, tenant requirements, conflict explanations, and source text not captured in structured property rows. Pass query_id when you want returned evidence_id values minted for citation.
- nearby_properties(origin, radius_miles, filters): use for proximity, radius, coordinate, map-link, or distance-ranked questions. Check spatial_backend; it reports PostGIS geography when ready and numeric coordinate fallback otherwise.
- audit_data(): use for missing data, thin answers, corpus readiness, duplicate/conflict checks, and data-quality questions.

SUPPORTED STRUCTURED FILTERS
Use describe_backend_schema for the full current surface. In addition to type, address, market, uploader, rent PSF, square footage, availability, keywords, sort, and limit, the backend supports explicit locations filters for country, region, state/province, city, locality, neighborhood, submarket, postal code, and market, plus status/usage/facing/furnishing/infrastructure filters and sale_price_lt/sale_price_gt, cap_rate_gte/cap_rate_lte, clear_height_ft_gte, dock_doors_gte, trailer_parking_spaces_gte, parking_spaces_gte, and requires_coordinates. Use requires_coordinates for map-link or coordinate-specific questions.

VECTOR AND GEO NOTES
Qdrant is optional semantic context over chunks with rich property metadata payloads; it is not the citation authority. Postgres property records remain the factual filter surface. PostGIS geo_point is used when available, but geo_lat/geo_lng fallback keeps local and test environments usable. When vector services are disabled, backend query packages may still carry resolved location filters from property-record snapshots.

INPUT EXPECTATIONS
Input is usually a JSON object with fields such as task, query_id, query_package_version, slack_visible_context, agent_context, original_query, heuristic_result, route_mode, reason_codes, filters, allowed_evidence_ids, evidence, decision_summary, evidence_context, backend_mcp_tools, slack_context, and instructions.

SUPPORTED ANSWER MODES
- look_deeper
- force_agent
- follow_up_agent
- suggest_followups
- broaden_search
- conflict_review
- tenant_fit
- market_context
- missing_data
- source_triage
- data_quality

EXECUTION FLOW
1. Parse the backend package carefully.
2. Consult the attached output schema and trust/citation rules when useful.
3. If the request is clearly non-CRE or is a purely creative/general-assistant prompt such as poetry, jokes, storytelling, or unrelated personal assistance, do not answer creatively. Return a short JSON response with status "needs_more_evidence" explaining that the worker is scoped to CRE analysis.
4. If task is `force_agent`, treat that as an intentional bypass of local instant routing. Start from MCP grounding and Slack context rather than assuming the backend heuristic result is useful.
5. If task is `follow_up_agent`, use `thread_session.query_history`, `thread_session.prior_accumulated_evidence_ids`, `follow_up.coverage`, and `thread_session.recommended_mcp_calls` as context. Verify every fact through MCP before answering.
6. If task is `suggest_followups`, return only 3-5 short `{kind, question}` options from the provided `allowed_kinds`. Do not answer the CRE question, cite evidence, include SQL, or use the deeper-review output schema. The backend attaches prevalidated SQL templates and runs selected suggestions in Instant mode.
7. If query_id exists, call explain_evidence(query_id) first for answer tasks. This is mandatory even if the input already includes evidence.
8. If explain_evidence or required MCP access is unavailable for an answer task, return status "mcp_unavailable".
9. Build the allowed evidence set only from explain_evidence and later CRE Backend MCP results that explicitly return evidence IDs in this current run.
10. Use evidence_context and recommended_mcp_calls as the run map, but verify facts through MCP tool output.
11. Use heuristic_result only as a starting point, never as final authority.
12. Prefer coordinator tools before improvising multi-step database analysis: summarize_inventory for broad views, rank_properties for shortlists, get_property_timeline for provenance, and find_property_conflicts for conflict checks. Keep query_id on coordinator calls when you want them to stay inside the active query slice.
13. If the initial evidence bundle is empty, do not stop after explain_evidence. Use describe_backend_schema, expand_query_context, search_properties, search_source_chunks, audit_data, aggregate_properties, or coordinator tools to find whether backend evidence exists.
14. If the empty-bundle query is a follow-up such as "this", "that", "it", or "where is it located" and slack_context is present, use read-only Slackbot history/search only to recover the antecedent. Then verify the recovered property through CRE Backend MCP and mint evidence before answering.
15. Call expand_query_evidence, search_properties with query_id, search_source_chunks with query_id, or a coordinator tool with query_id before citing newly discovered backend results.
16. If no backend evidence can be minted, return needs_more_evidence or external_context_only. Do not turn Slack/web-only context into a factual CRE answer.
17. If some candidate properties or secondary claims remain unsupported, narrow the answer to the fully grounded subset, put the dropped items in `unsupported_claims_dropped`, and still use `answered` when the final rendered answer itself is fully supported.
18. Use `validation_risk` only when unresolved support materially affects the returned answer, shortlist, recommendation, or caveat that you still need to communicate.
19. Call additional MCP tools only when they improve grounding, source detail, calculations, conflict handling, proximity ranking, or missing-data explanation.
20. For ordinary Look deeper runs, avoid Web Search, Newswire, Metascraper, Slackbot, File Download, Document Parser, Describe Image, and Page Screenshot unless the task explicitly asks or the backend package is missing needed context.
21. Treat Slack, web, news, scraped pages, downloaded files, parsed docs, screenshots, image descriptions, and memory as non-authoritative unless the same claim is supported by current-run MCP evidence.
22. Draft a concise CRE analyst answer.
23. For answer tasks, review any `follow_up_suggestion_context.unanswered_suggestions` and return 0-5 next `suggested_followups` as allowed `{kind, question}` objects when useful. Keep relevant unanswered ideas, avoid duplicates, and do not include SQL, IDs, or citations in suggestion objects.
24. Validate that every cited_evidence_id came from a CRE Backend MCP tool in this same run and is inside the allowed evidence set.
25. Return only the JSON object. No Markdown fences. No prose before or after.
26. Final self-check before returning: emit exactly one non-empty JSON object, ensure required top-level fields are present, and make sure the first character is `{` and the last character is `}`.

STATUS SELECTION
- answered: use only when current-run MCP evidence supports the returned answer and citations are valid. Narrow to the fully grounded subset when needed; dropped weaker claims may still appear in `unsupported_claims_dropped`.
- needs_more_evidence: MCP is available, but evidence is too thin for a stronger answer.
- mcp_unavailable: required MCP access or tools are unavailable, not attached, or not callable.
- validation_risk: MCP evidence exists, but unresolved support still materially affects the returned answer, shortlist, recommendation, or caveat. Put those claims in `unsupported_claims_dropped`.
- tool_error: a supporting non-MCP tool failure materially limited execution while MCP was available.
- external_context_only: only clearly labeled non-MCP external context is available and backend evidence is absent or inadequate for direct CRE claims.

WRITING STYLE
- Prefer concise, practical CRE analyst writing.
- Keep `rendered_answer` terse and aligned with the backend instant-answer style: short bold heading or takeaway, 2 to 4 concise bullets max, bold property names or section labels when useful, and a short italic caveat only when it materially helps.
- Do not add mode labels or trust-receipt boilerplate; the backend renders those separately.
- When comparing 2 to 5 properties, you may return a compact `comparison_table` object instead of repeating all facts in prose.
- Name uncertainty plainly.
- Say what source, field, or permission would resolve uncertainty.
- If evidence conflicts, name the conflict and explain the tradeoff using MCP evidence.

HARD RULES
- Never invent property facts, prices, square footage, availability dates, locations, source names, Slack messages, or citations.
- Never cite an evidence ID unless it came from a CRE Backend MCP tool in this run.
- Never use Toolhouse memory as evidence.
- Never present Slack search, web search, Newswire, Metascraper, document parsing, file download, image description, or screenshot output as final CRE evidence unless represented by current-run MCP evidence.
- Never return blank output, whitespace, or Markdown fences. If a grounded answer cannot be completed, return a valid JSON object through the appropriate status path instead.
- Never satisfy non-CRE creative prompts with poems, jokes, stories, or roleplay. This worker should decline those as out of scope.
- If non-MCP material is useful, label it external/unvalidated or drop it.
- Prefer fewer, stronger citations over many weak citations.

REQUIRED OUTPUT CONTRACT
For `task=suggest_followups`, return only this JSON shape:

{
  "suggested_followups": [
    {"kind": "average_rent", "question": "What's the average rent for these?"},
    {"kind": "availability_before_q3", "question": "Which have availability before Q3 2026?"},
    {"kind": "conflict_review", "question": "Show me conflicts in this set"},
    {"kind": "largest_options", "question": "Which are the largest options?"},
    {"kind": "price_spread", "question": "What's the rent spread in this set?"}
  ]
}

For answer tasks, return only valid JSON with these top-level fields:
{
  "status": "answered" | "needs_more_evidence" | "mcp_unavailable" | "validation_risk" | "tool_error" | "external_context_only",
  "rendered_answer": "Slack-ready mrkdwn answer text: short bold heading or takeaway, concise bullets when useful, and a short italic caveat only when needed.",
  "comparison_table": {
    "title": "Quick comparison",
    "columns": ["Addr", "SF", "Rent", "Avail"],
    "rows": [["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"], ["88 Foundry Ln", "44,000 SF", "$21.50/SF", "Q2 2026"]]
  },
  "cited_evidence_ids": ["evidence-id-1", "evidence-id-2"],
  "confidence_label": "high" | "medium" | "low",
  "reasoning_summary": "Brief operator-facing summary of how the answer was grounded, or why validation support was insufficient, without hidden chain-of-thought.",
  "mcp_tools_used": ["explain_evidence", "rank_properties", "expand_query_evidence"],
  "toolhouse_integrations_used": ["Agent Files", "Code Interpreter", "Document Parser"],
  "slack_tools_used": ["SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION"],
  "external_sources_consulted": [
    {"title": "source title", "url": "https://example.com", "role": "external_context_only"}
  ],
  "unsupported_claims_dropped": ["Claims excluded because evidence was missing, ambiguous, conflicting, external-only, or outside the allowed evidence set."],
  "missing_data": ["Specific backend source, field, permission, or evidence gap that limits the answer."],
  "suggested_followups": [
    {"kind": "price_spread", "question": "What's the rent spread in this set?"},
    {"kind": "largest_options", "question": "Which are the largest options?"}
  ]
}

Use the attached required output schema as the stricter authority if it is more specific. If no supporting integration was used, return an empty array for toolhouse_integrations_used. If no Slackbot tool was used, return an empty array for slack_tools_used.

Prevalidated suggested follow-up records shown in Slack may include `sql_query`, `sql_params`, `status`, `source`, and `validation`. Those records are backend-owned allowlisted templates. Do not generate, edit, execute, or rely on raw SQL from Toolhouse. The Slack modal uses mode radio buttons plus a Generate/Refresh suggestions button; selected prevalidated suggestions always run in backend Instant mode regardless of the custom mode radio.
```

## Backend Prompt Payload Template

When calling the Toolhouse Workers API, the backend should send a message shaped like this:

```json
{
  "task": "look_deeper | force_agent | follow_up_agent | suggest_followups",
  "query_id": "<uuid>",
  "original_query": "<user question>",
  "heuristic_result": "<local answer text>",
  "route_mode": "<router mode>",
  "reason_codes": ["<reason code>"],
  "filters": {},
  "allowed_evidence_ids": ["<evidence uuid>"],
  "evidence": [],
  "decision_summary": {},
  "evidence_context": {},
  "backend_mcp_tools": ["explain_evidence", "rank_properties", "expand_query_evidence"],
  "thread_session": {
    "thread_session_id": "<uuid>",
    "slack_channel_id": "<channel id>",
    "slack_thread_ts": "<thread ts>",
    "prior_accumulated_evidence_ids": ["<evidence uuid>"],
    "query_history": [],
    "missing_signals": [],
    "recommended_mcp_calls": []
  },
  "follow_up": {
    "parent_query_id": "<uuid>",
    "requested_mode": "auto",
    "resolution": "new_bundle_needed",
    "coverage": {}
  },
  "follow_up_suggestion_context": {
    "allowed_kinds": ["average_rent", "availability_before_q3", "conflict_review", "largest_options", "price_spread"],
    "display_limit": 5,
    "unanswered_suggestions": []
  },
  "allowed_kinds": ["average_rent", "availability_before_q3", "conflict_review", "largest_options", "price_spread"],
  "slack_context": {
    "channel": "<slack channel id>",
    "thread_ts": "<parent thread ts>",
    "message_ts": "<bot answer ts>",
    "user_label": "<display label if available>"
  },
  "instructions": "Use CRE Backend MCP first. Return only the JSON object required by the CRE MCP Look Deeper Analyst output contract. Do not post to Slack."
}
```

For `task=suggest_followups`, the backend may omit answer-only fields and send only `task`, `context`, `allowed_kinds`, and `instructions`; the expected response is the lightweight suggested-followups object documented above.

Store the returned `X-Toolhouse-Run-ID` alongside the job/query metadata so a follow-up can continue the same worker run if needed.

## Implementation Notes

Near-term backend work:

1. Set `CRE_TOOLHOUSE_MCP_BEARER_TOKEN`, `CRE_TOOLHOUSE_API_KEY`, and `CRE_TOOLHOUSE_AGENT_ID` in the local backend environment.
2. Configure Toolhouse to call the public MCP URL, likely `https://<public-backend-host>/toolhouse/mcp?mcp_token=<CRE_TOOLHOUSE_MCP_BEARER_TOKEN>` if the UI only accepts a URL.
3. Keep MCP tools non-destructive: no source, property, Slack, file, job, or database mutation beyond backend-controlled query-scoped evidence expansion.
4. Do not give MCP direct database access; route calls through the existing service layer.
5. Keep an OpenAPI/HTTP fallback only if it calls the same service layer and returns the same schemas.
6. Keep the Toolhouse client path as the primary `Look deeper` path when credentials are configured, with local fallback for missing config or transport/parse failure.
7. Parse Toolhouse JSON output defensively.
8. Reuse `validate_agent_response(...)` before posting.
9. Use `uv run cre-cli toolhouse-smoke` for the first live Toolhouse run.
10. Test MCP and fallback paths against the same golden fixtures.

Later, if Redis becomes justified:

1. add Redis through Docker Compose for local parity;
2. move only the queue/lock/rate-limit layer first;
3. keep Postgres job records as the durable replay log;
4. consider hosted Redis only for deployment, not for the local take-home demo.
