# Ideation — Part 2

## Goal of this document

Part 1 captured the architecture choices and product philosophy.

This document turns those decisions into an **implementation blueprint**:
- what modules exist
- what each module owns
- how data flows through the system
- how routing works
- how Slack interactions should behave
- how Toolhouse fits into the stack
- what to build first

The aim is to keep the codebase **backend-heavy, modular, and calm**:
a Docker Compose monolith with clearly separated internal services, not a Kubernetes or microservice sprawl.

---

## Build target

The system should feel like a **quietly elite CRE intelligence engine**.

Core behavior:
1. Ingest Slack messages and files.
2. Parse and normalize property knowledge.
3. Store raw provenance, structured facts, and semantic chunks.
4. Answer simple queries instantly using heuristics and structured DB queries.
5. Escalate ambiguous or deeper questions into Toolhouse agent mode.
6. Return a concise Slack answer with sources and a subtle escalation affordance.

---

## Concrete system modules

Use a modular monolith with these internal modules:

```text
app/
├── api/
├── slack/
├── ingestion/
├── extraction/
├── normalization/
├── enrichment/
├── indexing/
├── routing/
├── retrieval/
├── answering/
├── toolhouse/
├── db/
├── models/
└── utils/
```

### Module responsibilities

#### `app/slack/`
Owns the Slack integration layer:
- mention handling
- file upload events
- threaded replies
- message updates
- buttons / actions
- modal submissions if needed

#### `app/ingestion/`
Owns durable intake of Slack content:
- historical backfill
- message capture
- file fetch and storage
- deduplication
- job enqueueing

#### `app/extraction/`
Owns parsing raw files into text / tables:
- PDF text extraction
- CSV/XLSX row extraction
- plain text handling
- page / row references
- table detection where possible

#### `app/normalization/`
Owns canonical CRE field cleanup:
- addresses
- dates
- currency
- sqft
- property type labels
- availability labels
- source references

#### `app/enrichment/`
Owns value-add metadata:
- geocoding if used
- confidence scoring
- entity linking
- source priority
- recency metadata

#### `app/indexing/`
Owns retrieval indexing:
- embeddings
- chunk creation
- Qdrant writes
- metadata indexing
- keyword / text search support

#### `app/routing/`
Owns query classification and mode selection:
- instant answer
- hybrid retrieval
- agentic Toolhouse escalation

#### `app/retrieval/`
Owns search and evidence gathering:
- structured queries
- semantic search
- filter application
- reranking
- source assembly

#### `app/answering/`
Owns final response generation:
- formatting
- citations
- concise Slack output
- response variation for instant vs agentic mode

#### `app/toolhouse/`
Owns the boundary with Toolhouse:
- agent-facing tool definitions
- escalation payloads
- agent mode orchestration
- optional scheduled jobs

#### `app/db/`
Owns persistence:
- SQLAlchemy models
- migrations
- sessions
- repositories

#### `app/models/`
Owns typed business objects:
- `SourceDocument`
- `Chunk`
- `PropertyRecord`
- `EvidenceItem`
- `RoutingDecision`
- `AnswerPayload`

---

## Data model blueprint

The system should preserve both raw content and clean facts.

### 1) `SourceDocument`
Represents a Slack message, PDF, CSV, XLSX, or text attachment.

Fields:
- `id`
- `source_type`
- `slack_channel`
- `slack_user`
- `slack_ts`
- `file_name`
- `file_url`
- `raw_text`
- `raw_payload_hash`
- `posted_at`
- `status`

Purpose:
- audit trail
- dedup
- reprocessing
- provenance

### 2) `Chunk`
Represents a retrieval unit.

Fields:
- `id`
- `document_id`
- `chunk_index`
- `chunk_text`
- `page_number`
- `row_number`
- `section_name`
- `embedding_id`
- `metadata_json`

Purpose:
- semantic search
- exact source location
- evidence retrieval

### 3) `PropertyRecord`
Represents extracted CRE facts.

Fields:
- `id`
- `document_id`
- `address`
- `normalized_address`
- `property_type`
- `sq_ft`
- `price_per_sq_ft`
- `availability`
- `market`
- `geo_lat`
- `geo_lng`
- `source_page`
- `source_row`
- `confidence`

Purpose:
- fast filtering
- aggregation
- direct lookup
- distance queries later if needed

### 4) `EvidenceItem`
Represents the information used to answer a question.

Fields:
- `id`
- `query_id`
- `chunk_id`
- `property_record_id`
- `relevance_score`
- `matched_fields`
- `source_summary`

Purpose:
- answer traceability
- citations
- ranking explanation

### 5) `RoutingDecision`
Represents the path chosen for a user query.

Fields:
- `id`
- `query_text`
- `mode`
- `confidence`
- `reason_codes`
- `created_at`

Purpose:
- debug
- analytics
- fallback analysis
- future tuning

---

## Persistence strategy

Use **PostgreSQL** as the source of truth.

Store:
- raw event metadata
- normalized facts
- extracted records
- evidence
- routing decisions
- answer logs

Use **Qdrant** for semantic retrieval.

Store:
- chunk embeddings
- metadata filters
- source references

Use **Redis** only if you need:
- a queue
- rate-limited cache
- temporary job coordination

Do not spread state across too many systems.

---

## Ingestion pipeline

The ingestion pipeline should be asynchronous and replayable.

### Flow
1. Slack event arrives.
2. Store raw payload immediately.
3. Compute dedup hash.
4. Enqueue processing job.
5. Fetch file if there is one.
6. Parse and extract content.
7. Normalize and enrich.
8. Write structured data and chunks.
9. Generate embeddings.
10. Index into Qdrant.

### Important rule
Slack event handlers should be thin.

Do not parse files directly inside the webhook handler.

They should:
- acknowledge fast
- persist raw input
- enqueue downstream work

That keeps the bot responsive and reliable.

---

## Extraction pipeline

### PDFs
Use **PyMuPDF** first.

Capture:
- page text
- page number
- headings if available
- tables if extractable
- likely address / price / sqft lines

### CSV/XLSX
Use:
- `pandas`
- `openpyxl`

Capture:
- column names
- row values
- inferred data types
- empty / malformed cells
- row numbers for citations

### Slack text
Capture:
- channel
- author
- timestamp
- thread context
- inline property mentions
- file references

---

## Normalization rules

Normalize aggressively but conservatively.

### Fields to normalize
- addresses
- dates
- currency values
- sqft
- property type
- availability status
- file names
- market names

### Normalization examples
- `42 psf` -> `price_per_sq_ft = 42`
- `4,800 SF` -> `sq_ft = 4800`
- `Q3’26` -> `availability = 2026-Q3`
- `office tower`, `Class A office` -> `property_type = office`

### Why this matters
Heuristic answers depend on exact structured fields.

The cleaner the normalization, the stronger the fast path becomes.

---

## Enrichment rules

Enrichment should add useful metadata without overcomplicating the system.

### Useful enrichment
- source confidence
- recency
- file priority
- address parsing quality
- optional geocoding
- channel importance
- author name
- source page / row

### Optional later enrichment
- geospatial distance from a query anchor
- market / submarket tags
- entity linking across repeated listings

Keep the enrichment layer useful and lean, not bloated.

---

## Query routing blueprint

Routing is the core intelligence layer.

The system should classify each query into one of these:

- `lookup`
- `filter`
- `aggregation`
- `comparison`
- `proximity`
- `semantic_search`
- `summary`
- `synthesis`
- `uncertain`

### Routing modes
- **instant**: deterministic answer from structured data
- **hybrid**: structured + retrieval
- **agentic**: Toolhouse reasoning and deeper synthesis

### Routing signals
- numeric constraints
- aggregation words
- property type keywords
- temporal references
- source mentions
- proximity language
- ambiguity score
- semantic fuzziness

### Example router outputs

#### Example 1
Query:
“Total sqft of industrial properties in John’s file”

Decision:
- mode: `instant`
- confidence: high
- reason codes:
  - aggregation detected
  - numeric field detected
  - property type detected
  - source constraint detected

#### Example 2
Query:
“Which listings feel best for a logistics tenant near downtown?”

Decision:
- mode: `agentic`
- confidence: low-medium
- reason codes:
  - subjective intent
  - multiple criteria
  - synthesis needed

### Escalation path
If instant mode answers but the user wants more depth, the Slack UI should offer a subtle action such as:

- `Look deeper`

That button should route the same query plus the heuristic result into Toolhouse agent mode.

---

## Retrieval blueprint

### Instant mode retrieval
Use structured DB queries first.

The flow:
1. parse query into fields
2. filter Postgres records
3. compute aggregations if needed
4. attach source references
5. format Slack answer

### Hybrid retrieval
Use when exact data is insufficient.

The flow:
1. apply structured filters
2. semantic search in Qdrant
3. keyword matching for exact address / filename matches
4. rerank candidates
5. collect top evidence
6. format answer with citations

### Agentic retrieval
Use Toolhouse when:
- the question is vague
- multiple sources need synthesis
- semantic interpretation is needed
- the user explicitly clicks `Look deeper`

The agent should receive:
- original query
- heuristic result if any
- retrieval context
- evidence snippets
- confidence / reason metadata

That gives the agent a grounded starting point.

---

## Slack UX blueprint

The Slack experience should feel understated and sharp.

### Response style
- answer first
- sources second
- small action buttons
- minimal fluff

### Good response labels
Use subtle labels like:
- `Direct match`
- `Expanded search`
- `Look deeper`
- `Show sources`

Avoid:
- overly loud AI theatrics
- “thinking…” messages
- verbose pipeline dumps
- cringe mode names

### Recommended interaction pattern
1. Bot posts a concise answer.
2. If useful, it adds one or two actions:
   - `Look deeper`
   - `Show sources`
3. User escalates only when needed.

### Optional subtle metadata
You can show a very small footer such as:
- `Direct match • 420ms`
- `Expanded search • 3.9s`

Keep it understated.

---

## Toolhouse integration blueprint

Toolhouse should be the **agent shell**, not the data store.

### Toolhouse should own
- agentic fallback
- orchestration
- integration calls
- optional scheduled jobs
- Slack-facing agent behavior

### Your backend should own
- ingestion
- parsing
- normalization
- retrieval
- ranking
- answer assembly
- citations

### Tools to expose to Toolhouse
Expose clean backend tools such as:
- `search_properties`
- `get_property_by_address`
- `aggregate_sqft`
- `search_documents`
- `fetch_source_snippet`
- `lookup_file_mentions`
- `expand_context`

### Escalation payload
When the user clicks `Look deeper`, send:
- original user query
- heuristic result
- top evidence
- query metadata
- confidence score
- relevant sources

That makes the agent more accurate and less likely to wander.

---

## API surface blueprint

The backend can expose a small, focused API.

### Suggested endpoints

#### `POST /slack/events`
Receives Slack events.

#### `POST /slack/actions`
Receives button clicks and interactive UI actions.

#### `POST /ingest/backfill`
Starts a historical ingestion job.

#### `POST /query/route`
Returns routing decision and confidence.

#### `POST /query/answer`
Returns the final answer for a query.

#### `GET /sources/{id}`
Returns a source preview / provenance detail.

#### `GET /health`
Health check.

### Internal service boundaries
Even though this is a modular monolith, separate the code by responsibility so these endpoints call clean service layers.

---

## Background job blueprint

Use a worker for expensive tasks.

### Jobs
- file parsing
- chunking
- embedding generation
- enrichment
- backfill ingestion
- reindexing
- rebuilds after schema changes

### Worker characteristics
- idempotent
- retryable
- observable
- easy to replay

This is more important than fancy infra.

---

## Observability blueprint

Keep observability simple but real.

### Log
- ingestion start / finish
- parsing success / failure
- routing decision
- retrieval candidate counts
- answer latency
- escalation events
- button clicks

### Track
- number of instant answers
- number of agentic escalations
- heuristic override frequency
- query types that fail often

This will help in the follow-up conversation about trade-offs and future improvements.

---

## Testing blueprint

### Unit tests
- parsing
- normalization
- query classification
- aggregation
- citations formatting

### Integration tests
- Slack event to DB ingest
- ingest to retrieval
- query to answer
- button click escalation

### Golden-path demo tests
Keep a small curated set of questions and expected outputs.

Examples:
- exact lookup
- filtered search
- aggregation
- proximity-style search
- escalation through `Look deeper`

---

## Suggested build order

### Phase 1
- repo skeleton
- FastAPI app
- Slack events
- raw ingestion
- Postgres models

### Phase 2
- PDF / CSV / XLSX parsing
- normalization
- chunking
- Qdrant indexing

### Phase 3
- heuristic router
- instant answer mode
- Slack buttons
- source citations

### Phase 4
- Toolhouse integration
- `Look deeper` escalation
- better ranking / reranking
- demo polish

### Phase 5
- backfill
- logging
- README
- sample data
- video demo

---

## Minimum viable feature set

If scope gets tight, keep these:

- Slack mention support
- file ingestion
- PDF and CSV parsing
- PostgreSQL + Qdrant
- heuristic routing
- instant answers
- `Look deeper` escalation
- source citations
- clean README

These are the real differentiators.

---

## Future-leaning features for “two more weeks”

These are excellent follow-ups, but not core week-one scope:
- geospatial distance search
- reranking model
- OCR fallback
- richer entity resolution
- confidence dashboard
- analytics UI
- replayable event sourcing
- better market / neighborhood tagging

These are good answers for the follow-up question about what you would improve with more time.

---

## Final implementation principle

Build a system that is:

- **deterministic when it can be**
- **semantic when it should be**
- **agentic when it must be**
- **quiet in the UI**
- **loud in capability**

That is the whole product.

The best version is not the most verbose one.  
It is the one that feels like it knew what mattered before you asked twice.
