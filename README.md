# CRE Knowledge Engine

CRE Knowledge Engine is a Slack-native AI agent for Commercial Real Estate teams. It turns the messy information brokers already share in Slack - listing flyers, spreadsheets, field notes, corrections, market reports, and tenant requirements - into source-grounded answers inside Slack.

The product bet is simple: CRE users do not need another generic chatbot. They need a teammate that can say which property fits, where the fact came from, why one conflicting value won, and whether a deeper Toolhouse review stayed inside the evidence boundary.

## What It Proves

- Answers precise CRE questions from Slack-visible messages and files with citations.
- Parses PDFs, XLSX, CSV, text, images, and scanned documents into normalized property facts.
- Keeps field-level provenance for square footage, rent, availability, market, source rows/pages, Slack sender, channel, and timestamp.
- Uses deterministic Postgres retrieval for exact facts, filters, proximity, aggregation, and conflict resolution.
- Uses Qdrant plus local embeddings/reranking for hybrid source-text questions such as loading access or yard space.
- Exposes `Show sources` and `Look deeper` actions in Slack.
- Sends bounded Toolhouse synthesis through backend evidence tools, then validates every returned citation before posting.
- Provides replayable trust receipts for answers, golden evals, demo dry runs, and final submission checks.

Current proof points:

- `uv run pytest -q` passes 81 tests with no known failures or warning noise.
- `uv run cre-cli demo-doctor --live-toolhouse` returns `ready`, including public callback health and live Toolhouse validation with no local fallback.
- `uv run cre-cli demo-dry-run --live-toolhouse` passes the recording query sequence and returns replay commands for each answer.
- `uv run cre-cli secret-scan` scans source, docs, config, and sample files with 0 findings.

## Architecture

The system is easier to understand as five connected views: how Slack work enters the app, how evidence becomes structured knowledge, how answers are assembled, how Toolhouse is bounded, and how the submission proves itself.

### 1. Slack Intake And Job Loop

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef surface fill:#e8f2ff,stroke:#2563eb,color:#111827
    classDef app fill:#eef2ff,stroke:#4f46e5,color:#111827
    classDef jobs fill:#fff7ed,stroke:#ea580c,color:#111827
    classDef config fill:#f8fafc,stroke:#475569,color:#111827

    subgraph S[Slack workspace]
        direction TB
        S1[Designated CRE channels\nmessages, threads, files]
        S2[Broker asks @ai-cre-agent]
        S3[Actions\nShow sources + Look deeper]
        S4[Threaded answer\nshort answer + source links]
    end

    subgraph A[FastAPI Slack agent]
        direction TB
        A1[Slack routes\nverify signature, ack fast, dedupe retries]
        A2[Slack runtime + gateway\napp_mention, message, file_shared, actions]
        A3[Health + dependency endpoints\n/live, /ready, /health/deps]
        A5[Settings + migrations\n.env config, Alembic, SQLAlchemy models]
    end

    subgraph J[Postgres-backed job loop]
        direction TB
        J0[(ingestion_jobs\nqueued, running, succeeded, failed)]
        J1[answer_query]
        J2[ingest_slack_message / ingest_slack_file]
        J3[look_deeper]
        J4[worker lifecycle\nclaim, checkpoint, retry, post/update Slack]
    end

    S1 -->|events + files| A1
    S2 -->|app mention| A1
    S3 -->|button payload| A1
    A1 --> A2
    A2 --> J0
    J0 --> J1
    J0 --> J2
    J0 --> J3
    J1 --> J4 --> S4
    J2 --> J4
    J3 --> J4
    S4 --> S3
    A3 -.checks runtime + dependencies.-> J0
    A5 -.configures.-> A1
    A5 -.configures.-> J0

    class S1,S2,S3,S4 surface
    class A1,A2,A3 app
    class A5 config
    class J0,J1,J2,J3,J4 jobs
```

### 2. Ingestion To Evidence Spine

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef jobs fill:#fff7ed,stroke:#ea580c,color:#111827
    classDef ingest fill:#ecfdf5,stroke:#059669,color:#111827
    classDef store fill:#f8fafc,stroke:#475569,color:#111827
    classDef vector fill:#f0fdfa,stroke:#0f766e,color:#111827

    subgraph J[Ingestion jobs]
        direction TB
        J2[ingest_slack_message / ingest_slack_file]
        J4[worker lifecycle\nclaim, checkpoint, retry]
    end

    subgraph I[Ingestion + extraction]
        direction TB
        I1[Bounded Slack history backfill\nchannels, threads, files]
        I2[Continuous live ingestion\nCRE-signal messages + supported files]
        I3[Demo seeding + sync\npersonas, files, live Slack metadata]
        I4[Native parsers\nPDF, XLSX, CSV, text]
        I5[GLM-OCR\nimages + scanned PDFs]
        I6[CRE fact extraction\naddresses, rent, SF, dates, market]
    end

    subgraph E[Postgres evidence spine]
        direction TB
        E0[(System of record)]
        E1[source_documents\nslack_source_posts]
        E2[chunks]
        E3[property_records\nproperty_field_values]
        E4[queries\nevidence_items\nanswer_snapshots]
        E5[slack_events\ningestion_jobs\nagent_runs]
    end

    subgraph V[Indexable text]
        direction TB
        V1[Chunk text ready for retrieval]
        V2[Canonical CRE facts ready for filters]
    end

    J2 --> J4
    J4 --> I1
    J4 --> I2
    I3 --> I4
    I1 --> I4
    I2 --> I4
    I4 --> I5
    I4 --> I6
    I5 --> I6
    I6 --> E0

    E0 --- E1
    E0 --- E2
    E0 --- E3
    E0 --- E4
    E0 --- E5
    E2 --> V1
    E3 --> V2

    class J2,J4 jobs
    class I1,I2,I3,I4,I5,I6 ingest
    class E0,E1,E2,E3,E4,E5 store
    class V1,V2 vector
```

### 3. Retrieval And Answering

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef jobs fill:#fff7ed,stroke:#ea580c,color:#111827
    classDef store fill:#f8fafc,stroke:#475569,color:#111827
    classDef vector fill:#f0fdfa,stroke:#0f766e,color:#111827
    classDef answer fill:#faf5ff,stroke:#9333ea,color:#111827
    classDef surface fill:#e8f2ff,stroke:#2563eb,color:#111827

    subgraph J[Answer job]
        direction TB
        J1[answer_query]
    end

    subgraph E[Postgres evidence spine]
        direction TB
        E1[source_documents\nslack_source_posts]
        E2[chunks]
        E3[property_records\nproperty_field_values]
        E4[queries\nevidence_items\nanswer_snapshots]
    end

    subgraph V[Hybrid retrieval services]
        direction TB
        V1[Local embedding service\nqwen3-embedding-0_6b-q8_0]
        V2[(Qdrant\ncre_chunks, 1024-d cosine)]
        V3[Local reranker\nqwen3-reranker-0.6b]
        V4[Dependency fallback\nkeyword search when vector path is unavailable]
    end

    subgraph R[Answering + trust layer]
        direction TB
        R1[Query router\ninstant, hybrid, data quality, tenant fit]
        R2[Structured retrieval\nfilters, proximity, aggregation, source lookup, conflicts]
        R3[Hybrid chunk retrieval\nkeyword fallback + Qdrant/rerank]
        R4[Answer formatter\nSlack markdown, table, trust receipt]
        R5[Replay + eval surface\nexplain-query, replay-query, eval-golden]
    end

    subgraph S[Slack result]
        direction TB
        S4[Threaded answer\nshort answer + source links]
        S3[Actions\nShow sources + Look deeper]
    end

    E2 --> V1 --> V2 --> V3
    J1 --> R1
    R1 --> R2
    R1 --> R3
    R2 --> E1
    R2 --> E3
    R3 --> E2
    R3 --> V2
    V3 --> R3
    V4 -.fallback.-> R3
    R2 --> R4
    R3 --> R4
    R4 --> E4
    E4 --> R5
    R4 --> S4 --> S3

    class J1 jobs
    class E1,E2,E3,E4 store
    class V1,V2,V3,V4 vector
    class R1,R2,R3,R4,R5 answer
    class S3,S4 surface
```

### 4. Toolhouse Trust Boundary

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef surface fill:#e8f2ff,stroke:#2563eb,color:#111827
    classDef app fill:#eef2ff,stroke:#4f46e5,color:#111827
    classDef jobs fill:#fff7ed,stroke:#ea580c,color:#111827
    classDef store fill:#f8fafc,stroke:#475569,color:#111827
    classDef answer fill:#faf5ff,stroke:#9333ea,color:#111827
    classDef toolhouse fill:#fff1f2,stroke:#e11d48,color:#111827

    subgraph S[Slack action]
        direction TB
        S3[Look deeper button]
    end

    subgraph J[Deeper-review job]
        direction TB
        J3[look_deeper]
        J4[worker lifecycle\nclaim, checkpoint, retry, post/update Slack]
    end

    subgraph A[FastAPI boundary]
        direction TB
        A4[CRE Backend MCP\n/toolhouse/mcp + bearer/url-token auth]
    end

    subgraph T[Toolhouse deeper review]
        direction TB
        T1[Toolhouse Workers API]
        T2[Toolhouse agent]
        T3[Backend tool surface\nexplain evidence, search, aggregate, nearby, chunks, source detail, audit]
        T4[Citation validator\nallowed evidence IDs only]
        T5[Agent run trace\nraw response, parsed payload, validation, fallback]
    end

    subgraph E[Allowed evidence package]
        direction TB
        E1[source_documents\nslack_source_posts]
        E2[chunks]
        E3[property_records\nproperty_field_values]
        E4[queries\nevidence_items\nanswer_snapshots]
        E5[agent_runs]
    end

    subgraph R[Validated Slack update]
        direction TB
        R4[Answer formatter\nSlack markdown, table, trust receipt]
    end

    S3 --> J3 --> J4 --> T1 --> T2
    T2 -->|MCP calls| A4
    A4 --> T3
    T3 --> E1
    T3 --> E2
    T3 --> E3
    T3 --> E4
    T2 --> T4
    T4 --> T5 --> E5
    T4 -->|validated deeper answer| R4

    class S3 surface
    class A4 app
    class J3,J4 jobs
    class E1,E2,E3,E4,E5 store
    class R4 answer
    class T1,T2,T3,T4,T5 toolhouse
```

### 5. Reviewer Readiness Loop

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef ops fill:#fefce8,stroke:#ca8a04,color:#111827
    classDef app fill:#eef2ff,stroke:#4f46e5,color:#111827
    classDef store fill:#f8fafc,stroke:#475569,color:#111827
    classDef answer fill:#faf5ff,stroke:#9333ea,color:#111827
    classDef jobs fill:#fff7ed,stroke:#ea580c,color:#111827

    subgraph O[Operator + reviewer commands]
        direction TB
        O1[CLI / Make targets\nstatus, import, index, recover-demo]
        O2[Golden evals + demo doctor\nroute, evidence, deps, public callback]
        O3[Demo dry run + submission report\nrecording prompts, replay IDs, talking points]
        O4[Secret scan\nsource, docs, config, sample files]
        O5[Graphify map\n657 nodes, 1134 edges, 50 communities]
    end

    subgraph A[Runtime checks]
        direction TB
        A3[Health + dependency endpoints\n/live, /ready, /health/deps]
        A5[Settings + migrations\n.env config, Alembic, SQLAlchemy models]
    end

    subgraph J[State and workers]
        direction TB
        J0[(ingestion_jobs\nqueued, running, succeeded, failed)]
        J4[worker lifecycle\nclaim, checkpoint, retry, post/update Slack]
    end

    subgraph E[Persisted proof]
        direction TB
        E4[queries\nevidence_items\nanswer_snapshots]
        E5[slack_events\ningestion_jobs\nagent_runs]
    end

    subgraph R[Inspectable answer surface]
        direction TB
        R4[Answer formatter\nSlack markdown, table, trust receipt]
        R5[Replay + eval surface\nexplain-query, replay-query, eval-golden]
    end

    O1 --> J0 --> J4
    O1 --> A3
    O2 --> A3
    O2 --> R5
    O3 --> R4
    O3 --> R5
    O4 --> A5
    O5 --> O2
    A3 -.reads.-> E5
    R4 --> E4
    R5 --> E4
    E4 --> O3
    E5 --> O2

    class O1,O2,O3,O4,O5 ops
    class A3,A5 app
    class J0,J4 jobs
    class E4,E5 store
    class R4,R5 answer
```

The diagrams preserve the full runtime boundary while keeping each view small enough to scan. Graphify was rebuilt and checked against the code graph before this split, which is why the readiness loop also calls out the CLI, health, settings/migrations, worker lifecycle, Slack gateway, Toolhouse MCP auth, and Graphify proof surface.

The core boundary is intentional: Postgres is the system of record for sources, facts, evidence, jobs, answer snapshots, and agent runs. Toolhouse handles deeper synthesis, but the backend owns retrieval, tool outputs, and citation validation.

## The Slack Experience

A broker can ask:

| Slack prompt | What the agent demonstrates |
| --- | --- |
| `What properties do we have available near 123 Main Street?` | Proximity search over normalized property records with sourced nearby results. |
| `Show office buildings under $50/sq ft.` | Exact structured filtering that excludes higher-priced office inventory. |
| `Find listings that mention loading access or yard space.` | Hybrid retrieval over source text and field notes, with keyword fallback and Qdrant/rerank support. |
| `Why did you use 62k sq ft for Harbor Rd?` | Freshness and authority conflict handling with selected, supporting, and superseded evidence. |
| `Look deeper` | Toolhouse-backed synthesis over the allowed evidence bundle, with backend citation validation. |

Every factual answer includes a compact trust receipt: route label, evidence count, reason for selection, and source boundary. `Show sources` opens the evidence trail. `replay-query` reconstructs the stored answer snapshot outside Slack.

## Why It Is Credible

CRE data is full of small, expensive contradictions: one spreadsheet says 58,000 SF, a later correction says 62,000 SF, and a Slack thread explains which source to trust. This project treats those details as the product, not as prompt decoration.

The implementation favors boring reliability where facts matter:

- Slack is acknowledged quickly; slow parsing, indexing, answering, and Toolhouse calls run through background jobs.
- Live ingestion is conservative so generic chatter does not become source truth.
- Source appearances are modeled separately from canonical documents, so repeated Slack shares keep provenance without duplicating facts.
- Golden evals verify routes, expected addresses, source labels, reason codes, evidence order, and dependency state.
- Agent runs persist Toolhouse/local deeper-review traces, raw responses, parsed payloads, citation validation, fallback state, and rendered output.

## Try It Locally

This repo uses Python 3.12 and `uv`.

```bash
uv sync
make recover-demo
uv run cre-cli import-samples
uv run cre-cli index-chunks --reset
uv run cre-cli demo-doctor --skip-public-callback
```

Ask a local question:

```bash
uv run cre-cli ask "Show office buildings under $50/sq ft."
```

Replay the resulting answer:

```bash
uv run cre-cli replay-query <query-id>
```

Run the final readiness path:

```bash
make demo-check
make submission-report
```

For the live Slack demo, the current workstation path uses:

- FastAPI app: `http://127.0.0.1:8020`
- Public callback: `https://slack.aqwerty321.me`
- Qdrant collection: `cre_chunks`
- Embeddings: `qwen3-embedding-0_6b-q8_0`
- Rerank: `qwen3-reranker-0.6b`
- OCR: GLM-OCR at `http://127.0.0.1:5003`
- Toolhouse Agent ID: `0c2c4555-5d96-47e4-8e05-f956de7a102e`

Use `.env.example` as the non-secret template. Local `.env` values are intentionally excluded from the source secret scan.

## Reviewer Commands

```bash
uv run pytest -q
uv run cre-cli eval-golden
uv run cre-cli demo-doctor --live-toolhouse
uv run cre-cli demo-dry-run --live-toolhouse
uv run cre-cli secret-scan
uv run cre-cli submission-report --format markdown --output .runtime/submission-report.md
```

## Project Shape

- [app/main.py](app/main.py) creates the FastAPI app and worker lifecycle.
- [app/slack/](app/slack) owns Slack intake, answer rendering, source actions, and demo seeding.
- [app/ingestion/](app/ingestion) handles sample import, Slack backfill, live ingestion, source provenance, and quality checks.
- [app/extraction/](app/extraction) parses native files and routes image/scanned-document OCR.
- [app/retrieval/](app/retrieval) and [app/routing/](app/routing) implement structured, hybrid, tenant-fit, and data-quality retrieval.
- [app/answering/query_service.py](app/answering/query_service.py) writes queries, evidence items, answer snapshots, and explanation payloads.
- [app/toolhouse/](app/toolhouse) contains the Workers API client, bounded local fallback, MCP server, backend tools, and citation validator.
- [app/evaluation/](app/evaluation) provides golden evals, replay, demo doctor, demo dry run, secret scan, and submission report generation.
- [tests/](tests) covers golden answers, Slack loop behavior, ingestion, parsers, Toolhouse tools/client/MCP, and readiness commands.

## Submission Notes

- Demo video script: [docs/slack-demo-video-script.md](docs/slack-demo-video-script.md)
- Demo runbook: [docs/slack-demo-runbook.md](docs/slack-demo-runbook.md)
- Sample data and evaluation plan: [docs/sample-data-and-evaluation.md](docs/sample-data-and-evaluation.md)
- Production practices and trade-offs: [docs/production-practices.md](docs/production-practices.md)
- Toolhouse readiness checkpoint: [docs/toolhouse-readiness-checkpoint.md](docs/toolhouse-readiness-checkpoint.md)
- Generated submission report: [.runtime/submission-report.md](.runtime/submission-report.md)

Hardest part: keeping Slack ingestion, document extraction, retrieval, citations, Slack actions, and Toolhouse synthesis aligned around replayable evidence IDs.

Main trade-off: I chose a deterministic evidence spine and Postgres-backed jobs over adding orchestration frameworks for show. The result is less flashy internally, but more defensible in a CRE workflow where exact rent, square footage, availability, and source provenance matter.

With two more weeks: add production OAuth and multi-workspace permissions, admin review UI for low-confidence extraction, object storage for files, telemetry dashboards, external geocoding and drive-time search, retrieval benchmark snapshots, and retention/deletion workflows for Slack-originated data.