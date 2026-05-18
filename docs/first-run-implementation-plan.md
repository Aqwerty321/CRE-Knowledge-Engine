# First Run Implementation Plan

## Goal

Build the first runnable version of the ambitious MVP around the evidence spine, then extend it into a real Slack demo loop.

First milestone:

```text
import_samples -> normalize -> retrieve -> answer_with_citations
```

Ambitious demo milestone:

```text
backfill_demo_channel -> ingest_new_file -> hybrid_search -> look_deeper
```

## Local Dependency Audit

Checked on May 16, 2026.

Already available:

- Docker Engine: `29.4.3`
- Docker Compose: `5.1.3`
- Docker works for the current user without sudo
- Python: system `3.14.4`, plus `python3.12` available through `uv`
- `uv`: `0.11.6`
- `make`, `gcc`, `pkg-config`
- `file` / libmagic
- `pdftotext` from Poppler
- `cloudflared` for Slack webhook tunneling
- `git`, `curl`, `jq`, `openssl`

Missing for the current MVP:

- No required sudo-level dependency is missing.

Optional sudo installs:

- OCR future scope: `tesseract` and English language data.
- PostgreSQL client build tools only if we choose a source-built `psycopg` path. The planned first run uses `asyncpg`, so this is not required.

Recommended optional OCR install on Arch:

```bash
sudo pacman -S --needed tesseract tesseract-data-eng
```

No sudo is needed for Python dependencies; install those into the project venv with `uv` during implementation.

## First Run Stack Choices

| Concern | Choice | Reason |
| --- | --- | --- |
| Python runtime | `python3.12` via `uv` | Avoids Python 3.14 compatibility risk for parsing/data packages. |
| Dependency manager | `uv` | Already installed and fast. |
| Web/API | FastAPI | Slack event endpoints, health checks, and backend tools. |
| Slack | Slack Bolt for Python | Event handling, actions, threaded replies, message updates. |
| Database | PostgreSQL in Docker Compose | Source of truth for records, evidence, jobs, queries. |
| Vector store | Qdrant in Docker Compose | Hybrid retrieval for semantic golden query. |
| Queue | PostgreSQL-backed `ingestion_jobs` | Durable enough without Redis/Celery on the first run. |
| ORM | SQLAlchemy 2.x with `asyncpg` | Mature async Postgres path without requiring local libpq headers. |
| Migrations | Alembic | Credible schema evolution and reproducible setup. |
| Parsing | PyMuPDF, pandas, openpyxl, python-magic | PDF, CSV, XLSX, MIME/type handling. |
| Tests | pytest | Golden query and regression harness. |
| Tunnel | cloudflared | Already installed; exposes Slack webhook during local demo. |

## Implementation Phases

### Phase 1 - Project Scaffold

Create:

- `pyproject.toml`
- `.env.example`
- `docker-compose.yml`
- `Makefile`
- `app/` package layout
- `tests/` layout
- `sample-data/` layout

Initial app modules:

```text
app/
  api/
  answering/
  config/
  db/
  extraction/
  ingestion/
  indexing/
  models/
  normalization/
  retrieval/
  routing/
  slack/
  toolhouse/
  workers/
```

Deliverable: `make dev-up`, `make test`, and `make import-samples` commands exist, even if some commands are initially thin.

### Phase 2 - Database And Evidence Spine

Implement the canonical tables from [cre-data-dictionary.md](cre-data-dictionary.md):

- `source_documents`
- `slack_events`
- `chunks`
- `property_records`
- `property_field_values`
- `queries`
- `evidence_items`
- `answer_snapshots`
- `ingestion_jobs`

Add small support tables:

- `configured_channels`
- `sample_properties` or seeded coordinate lookup

Deliverable: the database can be created from migrations and reset locally.

Use [production-practices.md](production-practices.md) as the guardrail for P0/P1/P2 priorities, trust invariants, idempotency, status commands, and demo-readiness checks.

### Phase 3 - Sample Data And Importer

Create realistic local sample files from [sample-data-and-evaluation.md](sample-data-and-evaluation.md):

- 3 to 4 text-based PDFs
- 2 CSV inventories
- 1 XLSX tracker
- text notes / tenant requirements
- Slack-shaped message seed file

Implement `import_samples` so it writes the same source-document contract as live Slack ingestion:

- channel
- user
- timestamp
- file metadata
- source URL or permalink-like value
- content hash
- raw text pointer

Deliverable: `make import-samples` creates source documents and jobs, then extraction populates property records and chunks.

### Phase 4 - Extraction And Normalization

Implement deterministic extraction first:

- PyMuPDF for page-aware PDF text
- pandas for CSV and XLSX rows
- direct parsing for text and Slack message seeds

Normalize:

- address
- property type
- square footage
- price per square foot
- price basis
- availability
- dates
- seeded coordinates
- source references

Add bounded LLM fallback after deterministic extraction is working:

- fixed JSON schema
- source snippet required
- field confidence required
- method set to `semantic`
- no arithmetic

Deliverable: seeded properties from the sample manifest appear in `property_records` with provenance.

### Phase 5 - Structured Retrieval And Answers

Implement core retrieval before Qdrant:

- exact address lookup
- property type filters
- price and square-footage thresholds
- deterministic aggregation
- seeded proximity with Haversine distance
- source lookup by file, user, and date

Implement answer formatting:

- compact Slack text
- citations with file/message, page/row, user, date
- evidence item records
- no-result behavior

Deliverable: the first four golden queries pass without Qdrant or Slack.

### Phase 6 - Golden Query Harness

Turn golden queries into executable smoke tests:

- route mode assertion
- expected properties included
- excluded properties absent
- numeric totals exact
- evidence item attached
- source metadata present
- duplicate/freshness checks pass

Deliverable: `make golden` runs the sample import and verifies the key answers.

### Phase 7 - Qdrant Hybrid Retrieval

Add:

- chunk embedding interface
- Qdrant collection setup
- metadata payloads
- semantic chunk search
- keyword fallback
- weighted reranking using semantic score, structured match, authority, freshness, and extraction confidence

Deliverable: `Find listings that mention loading access or yard space` passes through Qdrant-backed hybrid retrieval.

### Phase 8 - Slack Integration

Add Slack Bolt endpoints:

- `app_mention`
- message/file event handling for configured channels
- interactive actions for `Show sources` and `Look deeper`

Use `cloudflared` for local webhooks:

```bash
cloudflared tunnel --url http://localhost:8000
```

Implement bounded live Slack backfill:

- configured channel IDs
- channel history pagination
- thread replies
- file listing
- file download
- checkpoints
- idempotency

Deliverable: demo channel can be backfilled, then a new message or file can be ingested after startup.

### Phase 9 - Toolhouse Integration

Expose backend tools:

- `search_properties`
- `aggregate_properties`
- `search_source_chunks`
- `get_source_detail`
- `nearby_properties`
- `explain_evidence`

Implement `Look deeper`:

- package original query
- include route decision
- include evidence IDs and source summaries
- let Toolhouse synthesize over evidence
- backend formats final answer through citation layer

Deliverable: logistics-tenant recommendation query can escalate to Toolhouse and remain sourced.

### Phase 10 - Polish And Demo Prep

Add:

- README setup/run instructions
- architecture diagram
- sample query table
- troubleshooting notes
- demo script
- final golden query run

Optional if time allows:

- `Broaden search` action
- ingestion status endpoint or CLI
- more duplicate/conflict cases
- route score breakdowns in logs

## Sudo Dependency Summary

Required now:

- none found.

Optional future-proof install:

```bash
sudo pacman -S --needed tesseract tesseract-data-eng
```

Do not install PostgreSQL, Qdrant, or Redis on the host for this project. They should run in Docker Compose.

Do not install Python packages globally. The implementation should create a local `.venv` using `uv` and `python3.12`.
