# Production Practices Reference

## Purpose

This document is the production-quality guardrail for the CRE Knowledge Engine. It translates the architecture in [final-implementation-spec.md](final-implementation-spec.md), [slack-toolhouse-integration.md](slack-toolhouse-integration.md), [cre-data-dictionary.md](cre-data-dictionary.md), [retrieval-routing-spec.md](retrieval-routing-spec.md), and [sample-data-and-evaluation.md](sample-data-and-evaluation.md) into concrete engineering practices.

Use it before implementing a module, before recording the demo, and before explaining production readiness in the follow-up discussion.

This guide was tightened through the council review in [production-practices-council-review.md](production-practices-council-review.md).

The goal is not enterprise completeness. The goal is to avoid embarrassing mistakes, preserve trust, and make the intelligence engine feel reliable, source-aware, and deliberately built.

## Production Posture

This is a take-home MVP, so production practice means disciplined local production readiness:

- deterministic evidence spine before agentic polish;
- graceful degradation when Slack, Qdrant, Toolhouse, or an LLM is unavailable;
- repeatable local setup and seeded golden checks;
- source-backed answers with no invented CRE facts;
- enough logs, statuses, and tests to explain what happened after a failure;
- Slack UX that feels calm, fast, and useful.

Do not optimize for theoretical scale before the demo path works. Do make every core decision easy to defend as the first version of a real production system.

## Priority Legend

Use these labels when implementing or reviewing the system:

| Priority | Meaning | Examples |
| --- | --- | --- |
| P0 demo spine | Must pass before recording. | Local import, schema, deterministic extraction, structured retrieval, citations, golden checks, safe secrets. |
| P1 live trust loop | Build once P0 is green. | Slack ack/dedupe/enqueue, bounded backfill, continuous ingestion, `Show sources`, status surfaces. |
| P2 intelligence polish | Demo differentiators after P1 is stable. | Qdrant hybrid query, freshness/authority, duplicate grouping, one evidence-bound Toolhouse `Look deeper`. |
| Defer | Two-week production hardening story. | OAuth install flow, multi-workspace tenancy, dashboards, OCR, external geocoding, admin UI, Qdrant alias rebuilds. |

When priorities conflict, choose the lowest number. A boring P0 path that always cites evidence beats a clever P2 path that cannot explain itself.

## First Build Execution Path

Build in this order. Do not advance to the next layer until the current one has a passing local check.

1. Scaffold local runtime.
    - Create `pyproject.toml`, `.env.example`, `docker-compose.yml`, `Makefile`, `app/`, `tests/`, and `sample-data/`.
    - Commands exist: `make dev-up`, `make migrate`, `make import-samples`, `make test`, and `make golden`.
2. Create the evidence spine.
    - Migrations create `source_documents`, `chunks`, `property_records`, `queries`, `evidence_items`, and `ingestion_jobs`.
    - `make migrate` can rebuild the schema from empty local Postgres.
3. Import and normalize sample data.
    - `make import-samples` writes Slack-shaped source documents.
    - Extraction creates chunks and property records with page, row, or Slack metadata.
4. Answer structured golden queries.
    - Exact lookup, numeric filter, aggregation, and seeded proximity pass.
    - Every answer writes `queries`, `evidence_items`, and an answer snapshot.
    - Qdrant, Slack, Toolhouse, and LLM fallback may be disabled.
5. Add demo layers only after structured golden queries pass.
    - Slack mention and `Show sources`.
    - Qdrant hybrid query with keyword fallback.
    - One Toolhouse `Look deeper` flow validated against evidence IDs.
    - Bounded Slack backfill and new message/file ingestion.

## Trust Invariants

These are the facts-and-evidence rules underneath every other practice:

1. No user-visible factual claim may be rendered unless it maps to stored evidence.
2. Every final answer stores an answer snapshot: query text, route, filters, rendered response, evidence IDs, dependency state, and model/prompt versions when used.
3. Every normalized field used in an answer preserves raw value, normalized value, source span, extraction method, confidence, and parser or model version when available.
4. Retrieval filters evidence by Slack workspace, configured channel, and any known visibility boundary before answer formatting or Toolhouse escalation.
5. Material conflicts are disclosed, not silently merged.
6. Golden tests verify claim-to-evidence coverage, not only expected result inclusion.

## Recording-Day Fallback Contract

Fallbacks are allowed when they are explicit and evidence-preserving:

- if live Slack backfill fails, demo local Slack-shaped import and explain that the same source-document contract powers backfill;
- if Qdrant fails, show structured answers and keyword fallback while marking semantic search degraded internally;
- if Toolhouse fails, hide or disable `Look deeper` and keep cited instant/hybrid answers working;
- if LLM extraction fails, deterministic extraction remains the only promoted fact path;
- if one sample source fails extraction, keep the failed source visible and demo from the passing golden set.

## Non-Negotiable Rules

1. Slack event and action handlers acknowledge within 3 seconds.
2. Long work is queued through `ingestion_jobs` or a query job path, never done inside the Slack ack path.
3. Every factual answer has stored evidence unless it is an explicit status or error response.
4. LLMs never perform authoritative arithmetic, filtering, distance calculation, or unsupported field invention.
5. PostgreSQL is the source of truth for facts, sources, jobs, queries, and evidence.
6. Qdrant can improve retrieval, but structured answers must still work without it.
7. Toolhouse receives evidence IDs and backend tools, not permission to invent primary facts.
8. File parsing failures preserve source records and failure state instead of disappearing.
9. Re-running imports, backfills, workers, and indexers must be idempotent.
10. Secrets never appear in committed files, logs, source citations, demo screenshots, or error messages.
11. Events, backfills, file jobs, and query context are restricted to configured demo channels unless explicitly expanded.
12. Toolhouse output is validated against known evidence IDs before posting to Slack.

## Build Gates

### Gate 1 - Local Evidence Spine

P0. Required before live Slack work:

- migrations create the core tables from [cre-data-dictionary.md](cre-data-dictionary.md);
- `make import-samples` writes Slack-shaped `source_documents`;
- extraction creates property records, chunks, and evidence-ready provenance;
- at least four structured golden queries pass without Qdrant;
- every rendered factual claim in those answers maps to one or more evidence items;
- answers include file/page, row, or Slack-message source summaries.

### Gate 2 - Reliable Slack Loop

P1. Required before claiming live ingestion:

- Slack signatures are verified;
- retry headers and duplicate event IDs are recorded;
- events from unconfigured channels are ignored or rejected before retrieval/ingestion work starts;
- app mentions and button actions ack quickly;
- backfill follows cursors and stores checkpoints after every page;
- thread replies are fetched separately from channel history;
- file metadata and file download are separate jobs;
- rate-limited methods honor `Retry-After` and resume from checkpoints.

### Gate 3 - Hybrid And Agentic Trust

P2. Required before demoing intelligence:

- Qdrant-backed semantic retrieval passes at least one golden query;
- keyword fallback is documented and tested for Qdrant downtime;
- source authority, freshness, and duplicate grouping affect presentation;
- `Look deeper` calls Toolhouse with evidence bundles and returns cited synthesis;
- Toolhouse citations are checked against the evidence ID whitelist before posting;
- `Show sources` explains why the answer used those facts.

### Gate 4 - Demo Release

P0 before recording. Required before recording:

- `make test` and `make golden` pass from a clean local setup;
- README setup commands are current;
- `.env.example` contains every required variable with safe placeholders;
- no secret-like values are in git status, logs, screenshots, or sample files;
- the demo channel has the expected files/messages;
- failure cases have human-readable Slack responses.

## Slack Production Practices

### Event Intake

- Use Slack Bolt to own all Slack-facing intake for the MVP.
- Verify request signatures on every Slack endpoint.
- Treat Slack payloads as untrusted external input; validate only fields needed for the current handler.
- Check configured channel allowlists before creating ingestion or retrieval work.
- Dedupe by top-level `event_id` for Events API payloads and by `(team_id, channel_id, ts)` for messages.
- Persist raw payload hashes for replay, not raw secrets or authorization tokens.
- Return success quickly after durable enqueue or no-op dedupe.

Store Slack delivery records separately from extracted source documents when possible. A lightweight `slack_events` or `slack_interactions` table should include event ID, team ID, channel ID, event type, retry headers, processed status, error code, and received timestamp.

### Ack Behavior

- Call `ack()` immediately for actions, commands, shortcuts, options, and view submissions.
- For Events API HTTP handlers, return a 2xx response within 3 seconds.
- Never fetch files, parse documents, call an LLM, query Toolhouse, or run Qdrant indexing before ack.
- If the payload is invalid but retrying will not help, record the reason and respond in a way that avoids repeated useless retries when appropriate.

### Retries And Idempotency

- Store Slack retry headers `x-slack-retry-num` and `x-slack-retry-reason` when present.
- Make duplicate retries harmless by checking the source/document/job unique keys before creating work.
- Job handlers should be safe after process restarts and partial completion.
- Use content hashes to dedupe repeated file uploads, but keep source-document links for each distinct Slack appearance when citation context differs.

### Rate Limits

- Follow cursor pagination for `conversations.history`, `conversations.replies`, file listing, and user/channel listing.
- Respect `Retry-After` for HTTP 429 responses at the method/workspace level.
- Keep Slack posting near one message per second per channel.
- Prefer one initial threaded reply plus later message update over many small messages.
- Backfill one to three configured channels; do not accidentally scan the whole workspace.

### Slack UX Polish

- Post answers in thread so the channel stays readable.
- Use a short acknowledgement for slow queries, then update the same thread when the answer is ready.
- Keep answers compact: direct answer first, sources second, actions third.
- Use `Direct match`, `Expanded search`, and `Deeper review` labels only when they clarify confidence.
- Include `Show sources` whenever evidence exists.
- Include `Look deeper` only when additional synthesis could improve the answer.
- For no results, state the filters applied and offer the nearest sourced alternative when confidence is acceptable.
- Avoid exposing route scores, stack traces, prompt text, or internal chain-of-thought style reasoning.

## FastAPI And Runtime Practices

### App Shape

- Keep FastAPI routes thin; route handlers should validate input, open scoped dependencies, and call service modules.
- Separate Slack endpoints, health endpoints, internal Toolhouse endpoints, and debug/status endpoints by router.
- Disable or protect debug-only routes in non-demo deployments.
- Use Pydantic settings for configuration and fail startup on missing required environment variables.

### Process Model

- For the take-home, Docker Compose is the process supervisor for local services.
- Use a single API process first; add more workers only after measuring memory and database connection needs.
- Run migrations once before app startup, not once per Uvicorn worker.
- Give the worker loop its own process/container so parsing or indexing cannot block Slack request handling.
- Add restart policies in Compose for the API, worker, Postgres, and Qdrant after the first runnable path is stable.

### Health Checks

Expose health endpoints with different depths:

- `/health/live`: process is running, no external dependencies required.
- `/health/ready`: database reachable and migrations current enough to serve requests.
- `/health/deps`: Postgres, Qdrant, Slack config presence, Toolhouse config presence, and embedding provider readiness.

The Slack request URL should depend on readiness; local dev scripts should make dependency state obvious.

### Error Handling

- Convert expected domain failures into typed errors with friendly Slack messages.
- Log unexpected exceptions with correlation IDs, not user-facing stack traces.
- Include `query_id`, `job_id`, `document_id`, `slack_channel_id`, and `slack_ts` in logs when available.
- Prefer partial recovery over all-or-nothing failure for extraction: keep any successfully extracted chunks and fields.

## PostgreSQL, SQLAlchemy, And Alembic Practices

### Schema And Migrations

- Every table in the evidence spine is created by Alembic migrations.
- Do not use `create_all()` as the real setup path after initial scaffolding.
- Add indexes at the moment a query path depends on them.
- Store timestamps as `timestamptz` and normalize display dates at the edge.
- Store raw payloads only when necessary; prefer hashes, selected metadata, and source pointers.

### Constraints

Use database constraints to enforce idempotency:

- messages: `(slack_team_id, slack_channel_id, slack_ts)`;
- files: `(slack_team_id, slack_file_id)`;
- jobs: `(source_document_id, job_type)` where practical;
- chunks: `(document_id, chunk_index)`;
- Qdrant point IDs: stable IDs derived from `chunk_id` or stored `embedding_id`.

Constraints are product features here: they prevent duplicate answers and make reruns safe.

### Session Scope

- Create the SQLAlchemy session factory once at app startup.
- Use one `AsyncSession` per request, worker job, or concurrent task.
- Do not share a session across asyncio tasks.
- Keep transactions short; avoid holding a transaction open while downloading files, calling Slack, embedding text, or invoking Toolhouse.
- Use context managers so commit, rollback, and close happen predictably.
- After any flush/commit failure, rollback or discard the session before continuing.

### Job Claiming

- Claim queued jobs atomically with row locking, status transition, and attempt increment.
- Store `started_at`, `updated_at`, `finished_at`, `attempt_count`, `last_error`, and `checkpoint_json`.
- Detect stuck `running` jobs by stale `updated_at` and move them to `retrying` within a bounded attempt limit.
- Make every job handler restartable from its checkpoint.
- Prefer small jobs over one huge backfill transaction.

## Ingestion And File Practices

### Source Lifecycle

Every source should move through explicit states:

```text
pending -> extracted -> indexed
    -> failed
    -> skipped
```

File download progress belongs in `ingestion_jobs.checkpoint_json` or file metadata rather than adding extra source statuses. A failed source remains visible with enough error detail to retry or explain.

### File Handling

- Separate Slack file metadata from downloaded content.
- Store original filename, MIME type, Slack file ID, size, uploader, channels, created timestamp, permalink, local path, and content hash.
- Validate file size and type before parsing.
- Keep downloaded files out of git.
- Use deterministic local paths based on source IDs or content hashes, not raw filenames alone.
- Do not log signed download URLs or authorization headers.

### Parsing

- Preserve page numbers for PDFs and row numbers for CSV/XLSX.
- Keep raw extracted text linked to the source document for replay.
- Normalize numeric fields from raw values; store both when useful.
- Treat OCR as optional/future unless the installed Tesseract path is explicitly wired and tested.
- Put parser version or extraction method in metadata so extraction changes can be explained.

## LLM And Extraction Guardrails

### Allowed LLM Uses

LLMs may be used for:

- bounded field candidate extraction from a provided source snippet;
- query classification assistance when deterministic router signals are inconclusive;
- Toolhouse synthesis over retrieved evidence;
- short answer wording after evidence is selected.

### Disallowed LLM Uses

LLMs must not:

- compute totals, averages, distances, filters, or date math;
- invent missing rents, square footage, availability, or sources;
- cite a source that was not retrieved and stored;
- decide freshness or authority without deterministic inputs;
- bypass the evidence item layer.

### Prompt And Output Discipline

- Use fixed JSON schemas for extraction.
- Require source snippet, field name, raw value, normalized value, confidence, and method.
- Reject or quarantine model output that fails schema validation.
- Promote semantic extraction fields only when they meet the configured confidence threshold and have a source span.
- Do not let low-confidence semantic fields drive golden-query answers unless a deterministic or manual-seed field corroborates them.
- Store model name, prompt version, and extraction method for replay.
- Cap input length and output length.
- Use deterministic temperature settings for extraction-style calls.

## Retrieval And Answer Practices

### Routing

- Route with explicit reason codes from [retrieval-routing-spec.md](retrieval-routing-spec.md).
- Log route mode, confidence, and top signals for every query.
- Tune thresholds against the golden queries before adding broad natural-language behavior.
- Prefer `instant` for exact facts, `hybrid` for fuzzy evidence, and `agentic` for synthesis or `Look deeper`.

### Evidence Assembly

- Every answer writes a `queries` row and associated `evidence_items`.
- Every final answer stores a replayable answer snapshot with rendered text, filters, route mode, reason codes, dependency state, evidence IDs, and model/prompt versions when used.
- Evidence bundles should include source document, chunk, property record, relevance score, matched fields, and display citation.
- If evidence conflicts, show the freshest or most authoritative fact first and mention the conflict when it matters.
- Group duplicate property mentions at answer time; do not silently merge facts from different sources.
- `Show sources` should expose the evidence chain compactly: source, page/row/message, extracted field, raw value, normalized value, and reason used when available.

### Answer Formatting

- Put the answer before explanation.
- Cite compactly with file/message, page/row, uploader/sender, channel, and date when available.
- Use tables only when they improve scanning in Slack.
- Do not show internal JSON, embedding scores, stack traces, or prompt details to users.
- If no answer is found, say so plainly and include the filters or source scope searched.

For conflict/freshness answers, include the reason for preferring a fact in plain language, such as `freshest correction`, `authoritative inventory row`, or `duplicate mention grouped with flyer`.

## Qdrant Practices

### Collection Design

- Use one collection for the workspace/demo corpus with payload filters before creating many collections.
- Name the collection and vector size from configuration.
- Match Qdrant distance metric to the embedding model expectation; use cosine for normalized text embeddings unless the provider says otherwise.
- Store payload fields needed for filtering and source joins: `document_id`, `chunk_id`, `source_type`, `property_type`, `normalized_address`, `posted_at`, `source_authority_score`, and `freshness_score`.
- Keep PostgreSQL as the canonical store for source text and facts; Qdrant payloads are retrieval aids.

### Indexing And Reindexing

- Use stable point IDs tied to chunks.
- Reindex by document before supporting full-corpus rebuilds.
- Track embedding model name/version in configuration and collection metadata.
- For the demo, recreate or reindex the local collection explicitly; for two-week hardening, build a new collection and atomically switch a Qdrant alias.
- If Qdrant is yellow/optimizing, keep structured answers available and log degraded semantic readiness.

### Failure Behavior

- If Qdrant is unavailable, fall back to keyword retrieval over stored chunks.
- If embedding generation fails for a chunk, mark the index job failed without losing the chunk.
- Do not let a vector search result become a final answer until it is joined back to PostgreSQL evidence.

## Toolhouse Practices

### Boundary

- Toolhouse is the deeper review path, not the source of truth.
- The backend owns facts, retrieval, evidence, citations, Slack intake, and deterministic answers.
- Toolhouse should call backend tools and return synthesis grounded in returned evidence.

### Tool Contracts

Each backend tool should have:

- a typed request schema;
- a typed response schema;
- explicit max result count;
- source/evidence IDs in the response;
- stable error codes;
- latency logging;
- tests with seeded data.

### Look Deeper Flow

The backend should pass Toolhouse:

- original query text;
- route decision and reason codes;
- evidence IDs and source summaries;
- allowed backend tools;
- clear instruction to cite only returned evidence.

The backend should format the final Slack message through the same answer/citation layer used by instant and hybrid answers.

Before posting Toolhouse output, the backend must validate that every cited fact maps to an allowed evidence ID. Unsupported claims should be dropped, rewritten as uncertainty, or replaced with a fallback answer. Toolhouse should not post directly to Slack for the MVP path.

## Security And Secrets

### Environment

- Commit `.env.example`, never `.env`.
- Validate required settings at startup.
- Use separate variables for Slack bot token, signing secret, app token if needed, database URL, Qdrant URL, embedding provider credentials, Toolhouse keys, and demo channel IDs.
- Avoid defaulting secrets to empty strings that make failures confusing.

### Slack Permissions

- Request only the scopes required for the demo channel path.
- Prefer one public demo channel unless private channel behavior is essential.
- Keep token revocation and reinstall as documented troubleshooting steps.
- Do not display private Slack links or user data beyond what the demo requires.

### Sensitive Data Handling

- Redact tokens, authorization headers, signed URLs, and full Slack payloads from logs.
- Do not send entire workspaces or unbounded channel history to LLMs.
- Use source snippets, not whole corpora, for extraction fallback.
- Keep local downloaded files and generated databases ignored by git.

### Pre-Recording Secret Hygiene

- Run a tracked-file secret scan before recording and before pushing.
- Do not record `.env`, Slack app token screens, Slack signing secret screens, tunnel logs containing URLs plus tokens, signed file download URLs, or provider dashboards with keys.
- Keep demo screenshots focused on Slack answers, source receipts, status output, and architecture docs.
- If a token or signed URL appears in a recording, rotate it before submission.

## Observability Practices

### Logging

Use structured logs with stable keys:

- `request_id`;
- `slack_event_id`;
- `query_id`;
- `job_id`;
- `document_id`;
- `chunk_id`;
- `route_mode`;
- `duration_ms`;
- `status`;
- `error_code`.

Logs should answer three questions: what was received, what path was chosen, and where did it fail or succeed?

### Metrics

Track lightweight counters and timings even if they only print locally at first:

- Slack ack latency;
- Slack event count by type;
- job count by status and type;
- job duration by type;
- parser failures by file type;
- query count by route;
- answer latency by route;
- evidence count per answer;
- Qdrant search latency;
- Toolhouse escalation latency;
- golden query pass/fail count.

### Tracing

After structured logs and `make status` exist, use OpenTelemetry-style spans around critical flows when implementation time allows:

```text
slack.event.receive
ingestion.job.claim
file.download
document.extract
property.normalize
chunk.index
query.route
retrieval.structured
retrieval.semantic
answer.format
toolhouse.look_deeper
```

Add attributes such as `job_type`, `source_type`, `route_mode`, `document_id`, and `query_id`. Record exceptions on spans and mark error status for failed operations.

### Status Surfaces

Low-effort high-value status surfaces:

- `make status` or an internal endpoint showing counts of sources, ready documents, failed jobs, indexed chunks, and Qdrant collection state;
- a recent failed jobs view with retry instructions;
- route reason logs for the latest query;
- a demo-readiness command that runs migrations, import, tests, and golden checks.

## Testing Practices

### Test Pyramid For This Project

- Unit tests for normalization, routing signals, source citation formatting, and distance math.
- Repository tests for Postgres constraints, idempotency, and job claiming.
- Parser tests for PDF/CSV/XLSX/text sample fixtures.
- Retrieval tests for structured filters, aggregations, proximity, duplicate grouping, and no-result behavior.
- Golden query tests from [sample-data-and-evaluation.md](sample-data-and-evaluation.md).
- Slack handler tests for ack/enqueue/dedupe behavior using representative payloads.
- Toolhouse contract tests for backend tool schemas and evidence-only responses.

### Golden Query Standards

Each golden query should assert:

- selected route;
- expected properties included;
- excluded properties absent;
- numeric totals exactly correct;
- at least one evidence item;
- every rendered factual claim maps to evidence;
- source file/page/row or Slack message metadata;
- configured-channel or visibility filtering is respected;
- material conflicts are disclosed when the query depends on the conflicted fact;
- graceful fallback path when Qdrant or Toolhouse is disabled.

### Regression Fixtures

Include deliberate edge cases:

- duplicate 120 Main flyer/message;
- Harbor Rd 58k vs 62k freshness conflict;
- office under `$50/SF` excluding 900 North Loop;
- industrial aggregation scoped to John;
- no-result query with nearest sourced alternative;
- Slack retry event that does not duplicate work.

## Docker Compose And Local Ops

### Compose Services

First runnable Compose stack should include:

- `api` for FastAPI and Slack endpoints;
- `worker` for ingestion, extraction, indexing, and query jobs if separated early;
- `postgres` with a named volume;
- `qdrant` with a named volume;
- optional `otel-collector` or log viewer only after core path works.

### Make Targets

Expected local commands:

```text
make dev-up
make dev-down
make migrate
make import-samples
make worker
make test
make golden
make status
make demo-check
```

Each target should be documented in README once it exists.

### Command Output Contracts

`make status` should show, at minimum:

- migration status;
- source count by status;
- failed job count by job type;
- `cre-cli eval-golden` route/evidence/citation checks;
- `cre-cli demo-doctor --skip-public-callback` local readiness checks;
- `cre-cli demo-dry-run --skip-public-callback` recording sequence checks;
- `cre-cli secret-scan` source/config/docs/sample secret hygiene;
- property record count;
- chunk count and indexed chunk count;
- Qdrant collection state when enabled;
- last query ID, route, evidence count, and latency when available.

`make demo-check` should run or verify:

- environment validation with secret redaction;
- migrations current;
- local sample import completed;
- structured golden queries pass with Qdrant disabled;
- hybrid golden query passes or reports keyword fallback;
- no evidence-free factual answers;
- downloaded/generated data is ignored by git;
- no obvious secret-like values are present in tracked files.

`make explain-query QUERY_ID=...` or `uv run cre-cli replay-query <query-id>` should show route decision, reason codes, filters, evidence IDs, source summaries, dependency state, model versions, rendered answer text, and any persisted agent-run traces.

### Operator Runbook For The Demo Path

| Workflow | Command or action | Healthy signal | If it fails |
| --- | --- | --- | --- |
| Fresh boot | `make dev-up && make migrate` | `/health/ready` passes; migrations current. | Inspect API logs, check `DATABASE_URL`, rerun migrations. |
| Sample import | `make import-samples` | Sources, chunks, property records, and extraction jobs created. | Run `make status`; retry failed extract jobs. |
| Golden checks | `make golden` | Structured queries pass with Qdrant disabled. | Inspect query/evidence records; fix extraction or routing before Slack. |
| Qdrant fallback | Stop Qdrant and run the fallback check. | Structured answers pass; semantic path reports degraded. | Verify keyword chunk search and dependency status. |
| Failed file | `make retry-source SOURCE_ID=...` | Source moves from failed work back to queued work, then indexed. | Preserve failure state; do not delete source rows by hand. |
| Stuck job | `make retry-stuck-jobs` or admin equivalent. | Stale `running` jobs move to `retrying` within attempt limits. | Inspect checkpoint and last error before resetting. |
| Slack backfill resume | Restart worker or run backfill command. | Cursor resumes from last checkpoint; no duplicate sources. | Check configured channels, Slack scopes, and rate-limit state. |
| Demo readiness | `make demo-check` | Migrations, import, tests, golden checks, fallback checks, and secret scan pass. | Do not record until the failing row is fixed or explicitly deferred. |

### Data Reset

- Provide an explicit local reset command for demo data.
- Make reset hard to run accidentally against a non-local database.
- Keep sample import deterministic so golden query outputs do not drift between runs.

## Demo Polish Checklist

### Demo Trust Receipt

Every recorded demo answer should be explainable through a small trust receipt:

- visible route label: `Direct match`, `Expanded search`, or `Deeper review`;
- compact source-backed answer before explanation;
- `Show sources` action with evidence IDs, file/message names, page/row, sender, date, and Slack link when available;
- one human-readable reason for the evidence choice, such as `freshest correction`, `authoritative inventory row`, or `duplicate mention grouped`;
- logged `query_id`, route reason codes, answer latency, and evidence count;
- replay path through `make explain-query QUERY_ID=...` or equivalent local command.

The demo should include at least one trust receipt for a conflict/freshness case, preferably Harbor Rd, and one degraded-mode case where structured answers still work without Qdrant or Toolhouse.

### Before Recording

- Run from a fresh clone or clean local reset.
- Run `make demo-check` and capture the pass output.
- Run `make submission-report` and keep `.runtime/submission-report.md` available for final review.
- Confirm Slack app request URL points at the current `cloudflared` URL.
- Confirm the demo channel contains the expected files and messages.
- Confirm source links, page numbers, row numbers, and sender names render cleanly.
- Confirm `Show sources` works on the answers shown in the video.
- Confirm `Look deeper` has a useful, sourced answer and a graceful fallback if Toolhouse is unavailable.

### What To Show

- Start with a local golden query result or status count to prove reproducibility.
- Show Slack answering a precise structured question.
- Show a source inspection action.
- Show a fuzzy or semantic query that demonstrates Qdrant.
- Show a freshness/duplicate case, ideally Harbor Rd.
- End with `Look deeper` over retrieved evidence.

### What To Avoid

- Do not record setup thrash, token screens, or Slack app settings unless needed.
- Do not show long raw JSON logs.
- Do not rely on a live LLM call as the only proof that the system works.
- Do not let Slack responses scroll past the evidence.
- Do not claim production scale that was not built; frame production practices as first-version discipline and next-step readiness.

## Failure Mode Matrix

| Failure | User-Facing Behavior | Internal Behavior |
| --- | --- | --- |
| Slack retry | No duplicate answer. | Dedupe event/source, log retry headers. |
| Slack rate limit | Existing answer remains; delayed update if needed. | Honor `Retry-After`, pause method/workspace, resume checkpoint. |
| File download fails | Source marked failed; retry can be mentioned in status. | Preserve metadata, error code, attempt count. |
| Parser fails | Answer ignores unsupported source unless partial text exists. | Store source failure and recoverable chunks. |
| LLM extraction invalid | Field is not promoted to facts. | Quarantine output with schema error. |
| Qdrant down | Structured answers still work; semantic path degrades. | Use keyword fallback, log degraded dependency. |
| Toolhouse down | `Look deeper` disabled or responds with fallback. | Keep instant/hybrid paths healthy. |
| DB migration missing | App not ready. | Readiness fails with clear migration message. |
| Secret missing | App fails fast on startup. | Config validation names missing variable, not value. |

## Two-Week Production Hardening Story

If interviewers ask what would change with two more weeks, use this as the production-oriented answer:

- add OAuth install flow and multi-workspace permission boundaries;
- replace local file storage with object storage and signed internal references;
- add admin review UI for failed/low-confidence extraction;
- add OCR and scanned brochure queue with clear quality thresholds;
- add external geocoding, radius search, and drive-time search;
- add full telemetry backend with dashboards and alerts;
- add retrieval benchmark snapshots and automated regression reports;
- add blue/green Qdrant alias rebuilds for embedding model changes;
- add production secret management and deployment pipeline;
- add data retention and deletion workflows for Slack-originated content.

## Final Pre-Ship Checklist

- [ ] No factual Slack answer can be emitted without evidence.
- [ ] Slack ack path has no file parsing, LLM, Qdrant indexing, or Toolhouse calls.
- [ ] Re-running sample import does not duplicate sources or facts.
- [ ] Backfill can resume from the latest checkpoint.
- [ ] Structured golden queries pass with Qdrant disabled.
- [ ] Hybrid golden query passes with Qdrant enabled.
- [ ] `Look deeper` answer is source-grounded and useful.
- [ ] Missing secrets fail startup clearly.
- [ ] Logs can trace a query from Slack event to evidence items.
- [ ] README commands match the current implementation.
- [ ] Demo video shows sources, freshness/duplicate logic, and a graceful failure or status surface.
