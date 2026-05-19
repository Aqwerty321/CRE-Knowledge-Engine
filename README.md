# CRE Knowledge Engine

CRE Knowledge Engine is a Slack app for commercial real estate teams. It reads the material brokers already trade in Slack - listing flyers, spreadsheets, field notes, corrections, market updates, and tenant requirements - and answers questions with the source trail attached.

The point is not to make Slack feel like a chatbot. The point is to help a broker ask, "Which properties fit?", then see the row, page, message, or correction that supports the answer. If two sources disagree, the app explains which one won and why. If the user asks for a deeper review, Toolhouse can reason over the same evidence bundle, but the backend still checks the citations before anything is posted.

## What The System Covers

- It answers CRE questions from Slack messages and files, and it cites where the answer came from.
- It parses PDFs, XLSX, CSV, text files, images, and scanned documents into usable property facts.
- It keeps the useful receipt for each fact: square footage, rent, availability, market, source row or page, Slack sender, channel, and timestamp.
- It uses Postgres for exact facts: filters, proximity, aggregation, source lookup, and conflict handling.
- It uses BM25S, PolyFuzz, TF-IDF character n-grams, optional Qdrant, and reranking when the question depends on source text, such as loading access or yard space.
- It gives the user two Slack actions: `Show sources` for the supporting rows/pages/messages, and `Look deeper` for a Toolhouse review.
- It validates Toolhouse citations against backend evidence IDs before posting a deeper answer.
- It can replay answers, run golden evals, execute readiness checks, and generate a submission report.

Current verification:

- `uv run pytest -q` passes 88 tests with no known failures or warning noise.
- `uv run cre-cli demo-doctor --live-toolhouse` returns `ready`, including public callback health and live Toolhouse validation with no local fallback.
- `uv run cre-cli demo-dry-run --live-toolhouse` passes the recording query sequence and returns replay commands for each answer.
- `uv run cre-cli secret-scan` scans source, docs, config, and sample files with 0 findings.

## Architecture

The full system is easier to read in pieces. These five diagrams show the main loops: Slack intake, ingestion, retrieval, Toolhouse review, and the verification surface around the runtime.

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

### 2. Ingestion To Evidence Store

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
        I3[Seed data + sync\npersonas, files, live Slack metadata]
        I4[Native parsers\nPDF, XLSX, CSV, text]
        I5[GLM-OCR\nimages + scanned PDFs]
        I6[CRE fact extraction\naddresses, rent, SF, dates, market]
    end

    subgraph E[Postgres evidence store]
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

    subgraph E[Postgres evidence store]
        direction TB
        E1[source_documents\nslack_source_posts]
        E2[chunks]
        E3[property_records\nproperty_field_values]
        E4[queries\nevidence_items\nanswer_snapshots]
    end

    subgraph V[Hybrid retrieval services]
        direction TB
        V0[Alias expansion\nretrieval_config.json]
        V1[Local lexical stack\nBM25S + substring]
        V2[Fuzzy stack\nPolyFuzz edit distance + TF-IDF char n-grams]
        V3[RRF fusion\nrank-based merge + matched-term gate]
        V4[Optional semantic stack\nQdrant + local reranker]
        V5[Layer status\ncontributors, disabled deps, expansion terms]
    end

    subgraph R[Answering + source checks]
        direction TB
        R1[Query router\ninstant, hybrid, data quality, tenant fit]
        R2[Structured retrieval\nfilters, proximity, aggregation, source lookup, conflicts]
        R3[Hybrid chunk retrieval\nlocal fusion + optional vector/rerank]
        R4[Answer formatter\nSlack markdown, table, source receipt]
        R5[Replay + eval surface\nexplain-query, replay-query, eval-golden]
    end

    subgraph S[Slack result]
        direction TB
        S4[Threaded answer\nshort answer + source links]
        S3[Actions\nShow sources + Look deeper]
    end

    E2 --> V0 --> V1 --> V3
    V0 --> V2 --> V3
    E2 -.when enabled.-> V4 --> V3
    V3 --> V5
    J1 --> R1
    R1 --> R2
    R1 --> R3
    R2 --> E1
    R2 --> E3
    R3 --> E2
    R3 --> V0
    V3 --> R3
    V5 --> E4
    R2 --> R4
    R3 --> R4
    R4 --> E4
    E4 --> R5
    R4 --> S4 --> S3

    class J1 jobs
    class E1,E2,E3,E4 store
    class V0,V1,V2,V3,V4,V5 vector
    class R1,R2,R3,R4,R5 answer
    class S3,S4 surface
```

### 4. Toolhouse Can Review, Not Invent

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

    subgraph A[Backend-owned gate]
        direction TB
        A4[CRE Backend MCP\n/toolhouse/mcp + bearer/url-token auth]
    end

    subgraph T[Toolhouse deeper review]
        direction TB
        T1[Toolhouse Workers API]
        T2[Toolhouse agent]
        T3[Backend tool surface\nexplain evidence, search, aggregate, nearby, chunks, source detail, audit]
        T4[Citation check\nallowed evidence IDs only]
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
        R4[Answer formatter\nSlack markdown, table, source receipt]
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

### 5. Verification And Readiness Loop

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef ops fill:#fefce8,stroke:#ca8a04,color:#111827
    classDef app fill:#eef2ff,stroke:#4f46e5,color:#111827
    classDef store fill:#f8fafc,stroke:#475569,color:#111827
    classDef answer fill:#faf5ff,stroke:#9333ea,color:#111827
    classDef jobs fill:#fff7ed,stroke:#ea580c,color:#111827

    subgraph O[Operator + verification commands]
        direction TB
        O1[CLI / Make targets\nstatus, import, index, recover-demo]
        O2[Golden evals + readiness doctor\nroute, evidence, deps, public callback]
        O3[Dry run + submission report\nrecording prompts, replay IDs, talking points]
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
        R4[Answer formatter\nSlack markdown, table, source receipt]
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

The diagrams are split on purpose. The first five show the running system without turning everything into one unreadable graph. The README coverage was checked against a fresh Graphify rebuild so the less-visible pieces remain represented: CLI commands, health checks, settings and migrations, the worker loop, the Slack gateway, Toolhouse MCP auth, and the Graphify map itself.

The key rule is simple: Postgres keeps the sources, facts, jobs, selected evidence, answer snapshots, and Toolhouse run logs. Toolhouse can write the deeper read, but it has to stay inside the evidence package the backend already selected.

## How Data Gets In

The app has three ways to learn about CRE data: a local sample import for repeatable demos, a bounded historical Slack backfill, and live Slack events. All three paths are shaped into the same internal dataset model before parsing, extraction, storage, and indexing. That is intentional: a golden query against local sample data should exercise the same tables and answer code as a query against live Slack data.

```mermaid
%%{init: {"flowchart": {"curve": "basis", "nodeSpacing": 34, "rankSpacing": 46}} }%%
flowchart LR
    classDef entry fill:#e8f2ff,stroke:#2563eb,color:#111827
    classDef gate fill:#fff7ed,stroke:#ea580c,color:#111827
    classDef resolve fill:#eef2ff,stroke:#4f46e5,color:#111827
    classDef parse fill:#ecfdf5,stroke:#059669,color:#111827
    classDef store fill:#f8fafc,stroke:#475569,color:#111827
    classDef quality fill:#fefce8,stroke:#ca8a04,color:#111827

    subgraph E[Entry points]
        direction TB
        E1[Local sample import\nmanifest + sample files]
        E2[Historical Slack backfill\nrecent channel history + thread replies]
        E3[Live Slack events\nmessage + file_shared callbacks]
    end

    subgraph G[Gate and queue]
        direction TB
        G1[Allowed channels + channel policy\ndisabled, files_only, listings_only, evidence]
        G2[Noise checks\nbots, empty events, unsupported subtypes, query-like chatter]
        G3[(slack_events\nretry metadata + payload hash)]
        G4[(ingestion_jobs\nmessage/file checkpoints)]
    end

    subgraph R[Resolve source]
        direction TB
        R1[Message checkpoint\npermalink + raw Slack text]
        R2[File checkpoint\nfiles.info + private download]
        R3[SampleDatasetModel\nsame shape for sample + live]
    end

    subgraph P[Parse and extract]
        direction TB
        P1[Native parsers\nCSV rows, XLSX sheets, PDF pages, text]
        P2[OCR fallback\nGLM-OCR for images + scanned PDFs]
        P3[CRE signal and fact extraction\naddress, type, SF, rent, availability, market]
    end

    subgraph S[Persist and index]
        direction TB
        S1[(source_documents)]
        S2[(slack_source_posts)]
        S3[(chunks\npage, row, section)]
        S4[(property_records)]
        S5[(property_field_values)]
        S6[Optional vector indexing\nQdrant embedding IDs]
        S7[Quality report\nmissing fields, context-only sources, conflicts]
    end

    E1 --> R3
    E2 --> G1
    E3 --> G1
    G1 --> G2
    G2 --> G3
    G3 --> G4
    G4 --> R1
    G4 --> R2
    R1 --> R3
    R2 --> R3
    R3 --> P1
    P1 --> P2
    P1 --> P3
    P2 --> P3
    P3 --> S1
    P3 --> S2
    P3 --> S3
    P3 --> S4
    P3 --> S5
    S3 --> S6
    S1 --> S7
    S4 --> S7

    class E1,E2,E3 entry
    class G1,G2,G3,G4 gate
    class R1,R2,R3 resolve
    class P1,P2,P3 parse
    class S1,S2,S3,S4,S5,S6 store
    class S7 quality
```

Historical backfill is deliberately bounded. The worker asks Slack for recent channel history, walks thread replies, and imports only messages or files that pass the same channel policy and CRE-signal checks used by live events. It counts what it saw and what it imported, but it does not treat generic conversation as evidence just because it appeared in a configured channel.

Live ingestion is also conservative. Each Slack delivery is recorded in `slack_events` with retry metadata and a payload hash. Duplicate Slack event IDs are ignored, unconfigured channels are skipped, and allowed events become `ingestion_jobs` with enough checkpoint data to replay the work: team, channel, user, message timestamp, thread timestamp, raw text, or file metadata.

Message jobs and file jobs converge quickly. A message job resolves the Slack permalink and stores the message text. A file job resolves Slack file metadata, downloads supported files into the local Slack download directory, and records file name, MIME type, Slack file ID, source URL, and local path. From there both paths use `SampleDatasetModel`, so local demos and live Slack ingestion share the same importer.

Parsing is source-aware. CSV files become row chunks. XLSX files become sheet-and-row chunks. PDFs keep page numbers when text extraction works; scanned PDFs and images go through GLM-OCR when OCR is enabled. Text files and Slack messages stay as text chunks. Those chunks feed heuristic CRE extraction for addresses, property type, square footage, rent, availability, market, source authority, freshness, and confidence.

Import is an upsert, not a blind append. The importer checks Slack file IDs, Slack message timestamps, local paths, and content hashes to reuse existing sources where appropriate. Before re-importing a source, it clears old child chunks, property records, and source-scoped jobs, then writes fresh chunks, property records, field values, Slack source appearances, and succeeded extract/index job records. If vector indexing is enabled, new chunk IDs are embedded and written to Qdrant.

There is also a cleanup path for live Slack storage. It can remove old Slack-message context that never produced property facts, release old file-download paths from source records, and delete orphaned local downloads under configured retention windows. It skips sources with active jobs and keeps property-backed sources intact.

The quality checks are part of ingestion, not an afterthought. The importer records validation warnings for duplicate source IDs, missing source text, duplicate chunk indexes, property rows pointing at missing chunks, sources without property records, and property records missing important fields. The data-quality answer later reports those gaps directly to the user.

## How Data And Routing Work

The implementation follows one rule: if the app says a fact in Slack, that fact should point back to a stored source, a normalized property record, or an evidence item. The core code is in [app/models/core.py](app/models/core.py), [app/routing](app/routing), [app/retrieval](app/retrieval), [app/answering/query_service.py](app/answering/query_service.py), and [app/toolhouse](app/toolhouse).

### Database Schema

```mermaid
erDiagram
    SOURCE_DOCUMENTS ||--o{ SLACK_SOURCE_POSTS : appears_as
    SOURCE_DOCUMENTS ||--o{ CHUNKS : splits_into
    SOURCE_DOCUMENTS ||--o{ PROPERTY_RECORDS : extracts
    CHUNKS ||--o{ PROPERTY_RECORDS : supports
    PROPERTY_RECORDS ||--o{ PROPERTY_FIELD_VALUES : explains_fields
    QUERIES ||--o{ EVIDENCE_ITEMS : selects
    SOURCE_DOCUMENTS ||--o{ EVIDENCE_ITEMS : cites_document
    CHUNKS ||--o{ EVIDENCE_ITEMS : cites_chunk
    PROPERTY_RECORDS ||--o{ EVIDENCE_ITEMS : cites_fact
    QUERIES ||--o{ ANSWER_SNAPSHOTS : snapshots
    QUERIES ||--o{ AGENT_RUNS : escalates
    SOURCE_DOCUMENTS ||--o{ INGESTION_JOBS : queues

    SOURCE_DOCUMENTS {
        uuid id PK
        string source_type
        string slack_team_id
        string slack_channel_id
        string slack_ts
        string slack_file_id
        string file_name
        text raw_text
        string content_hash
        datetime posted_at
        string status
    }

    SLACK_SOURCE_POSTS {
        uuid id PK
        uuid source_document_id FK
        string post_key
        string post_type
        string slack_channel_id
        string slack_ts
        string slack_file_id
        datetime posted_at
    }

    CHUNKS {
        uuid id PK
        uuid document_id FK
        int chunk_index
        text chunk_text
        int page_number
        int row_number
        string section_name
        string embedding_id
        json metadata_json
    }

    PROPERTY_RECORDS {
        uuid id PK
        uuid document_id FK
        uuid chunk_id FK
        string address
        string normalized_address
        string property_type
        int sq_ft
        decimal price_per_sq_ft
        string availability
        date availability_date
        string market
        decimal geo_lat
        decimal geo_lng
        decimal source_authority_score
        decimal freshness_score
        string duplicate_group_key
    }

    PROPERTY_FIELD_VALUES {
        uuid id PK
        uuid property_record_id FK
        string field_name
        text raw_value
        text normalized_value
        decimal confidence
        string method
        text source_span
        string extractor_version
    }

    QUERIES {
        uuid id PK
        string slack_channel_id
        string slack_user_id
        text query_text
        string route_mode
        decimal route_confidence
        array reason_codes
        datetime created_at
    }

    EVIDENCE_ITEMS {
        uuid id PK
        uuid query_id FK
        uuid document_id FK
        uuid chunk_id FK
        uuid property_record_id FK
        decimal relevance_score
        array matched_fields
        text source_summary
    }

    ANSWER_SNAPSHOTS {
        uuid id PK
        uuid query_id FK
        text rendered_answer
        string route_mode
        json filters_json
        array evidence_ids
        json dependency_state_json
        json model_versions_json
    }

    AGENT_RUNS {
        uuid id PK
        uuid query_id FK
        string provider
        string status
        string answer_mode
        json allowed_evidence_ids_json
        json cited_evidence_ids_json
        json response_payload_json
        json validation_json
        text fallback_reason
        text rendered_answer
    }

    SLACK_EVENTS {
        uuid id PK
        string slack_event_id
        string slack_team_id
        string event_type
        int retry_num
        string payload_hash
        string status
        datetime received_at
        datetime processed_at
    }

    INGESTION_JOBS {
        uuid id PK
        string job_type
        uuid source_document_id FK
        string status
        int attempt_count
        json checkpoint_json
        text error_message
        datetime started_at
        datetime finished_at
    }
```

How the schema is meant to be read:

- `source_documents` is the canonical source table. It covers Slack messages, thread replies, PDFs, CSVs, XLSX files, text notes, and OCR output.
- `slack_source_posts` records where a source showed up in Slack, so repeated shares keep their own channel, sender, timestamp, and permalink context.
- `chunks` holds the text used for search. Page, row, section, embedding ID, and metadata stay attached to the chunk.
- `property_records` stores facts as they appeared in a source. It does not try to merge everything into one perfect property entity too early. Likely duplicates are grouped with `duplicate_group_key` and resolved when an answer is built.
- `property_field_values` keeps the field-level audit trail: raw value, normalized value, confidence, method, source span, and extractor version.
- `queries`, `evidence_items`, and `answer_snapshots` are the answer trail. `Show sources`, `explain-query`, `replay-query`, and Toolhouse escalation all read from that trail.
- `agent_runs` stores the deeper-review trace: allowed evidence IDs, cited evidence IDs, parsed response, validation result, fallback reason, raw response, and final rendered answer.
- `slack_events` and `ingestion_jobs` keep Slack acknowledgement separate from slow work.

### How Routing Works

```mermaid
flowchart LR
    Q[Slack question] --> P[build_query_plan]
    P --> S{Route decision}
    S -->|instant| I[Structured Postgres path]
    S -->|hybrid| X[Alias expansion\nquery-time only]
    X --> H[Local hybrid retrieval\nBM25S, substring, PolyFuzz, TF-IDF]
    H --> F[RRF fusion\nrank merge + feature-term gate]
    F --> O[Optional rerank hook\nQdrant/local reranker when enabled]
    S -->|failed| U[Supported-pattern response]
    I --> E[EvidenceItem rows]
    O --> E
    U --> A[AnswerSnapshot]
    E --> A
    A --> B[Slack answer blocks\nsource receipt + actions]
    B --> D[Show sources]
    B --> L[Look deeper]
    L --> T[Toolhouse agent mode\nallowed evidence bundle]
```

The router is small by design. For each question it writes down the route, query type, confidence, reason codes, and filters it used. A few golden paths cover the highest-value operating questions. The generic query constructor handles the broader cases: property type aliases, known addresses, markets, uploader names, keywords, price and size thresholds, availability windows, aggregation, sorting, limits, missing-data terms, and tenant-fit wording.

| Query class | Route | What happens |
| --- | --- | --- |
| Proximity | `instant` | Recognizes seeded anchors like `123 Main Street`, computes Haversine distance from stored coordinates, sorts nearest available properties, and cites the supporting source rows. |
| Numeric filters | `instant` | Turns prompts like office under `$50/SF` into SQL predicates over `property_type` and `price_per_sq_ft`. |
| Aggregation | `instant` | Resolves source/uploader references such as John's industrial files, dedupes by `duplicate_group_key`, and sums `sq_ft` in Postgres. |
| Exact/source lookup | `instant` | Matches normalized address plus field value, then returns the source rows/pages where the value appeared. |
| Conflict review | `hybrid` | Uses a duplicate group such as Harbor Rd, orders candidates by source authority, freshness, and posting time, then labels evidence as selected, supporting, or superseded. |
| Loading or yard language | `hybrid` | Expands aliases such as dock doors, truck court, and trailer parking, then fuses BM25, substring, PolyFuzz edit distance, TF-IDF character n-gram, and optional Qdrant/rerank candidates. |
| Generic structured search | `instant` | Builds a transparent query constructor with conditions, sort, and limit, then returns deduped structured matches. |
| Tenant fit | `hybrid` | Runs a local heuristic over price, size, availability, source quality, and logistics terms, then invites `Look deeper` for Toolhouse review. |
| Data quality | `instant` | Scans indexed sources and property rows for missing fields, sources without chunks/properties, and duplicate groups with conflicting numeric facts. |
| Unsupported | `failed` | Refuses to guess and returns the supported query patterns currently covered. |

One important detail: `hybrid` does not mean the agent is improvising. It still means backend retrieval. The answer service finds the evidence, writes the evidence rows, records dependency state, and only then posts to Slack.

### Scoring And Ranking

The ranking rules are meant to be easy to audit:

- Structured matches score field coverage plus source quality: matched-field count, `source_authority_score`, `freshness_score`, and extraction confidence. Dedupe keeps the strongest row per `duplicate_group_key`.
- Sort requests are explicit: cheapest sorts by `price_per_sq_ft`, largest by `sq_ft`, and soonest availability by `availability_date`.
- Generic structured searches return the top deduped records after filters and sort. Exact lookups can keep multiple rows so source agreement or conflict is visible.
- Loading-access retrieval uses configurable alias expansion, BM25S lexical ranking, PolyFuzz edit-distance matching, TF-IDF character n-grams, optional Qdrant candidates, and Reciprocal Rank Fusion. A listing that matches multiple concrete feature terms still outranks a weaker partial match, all else equal.
- Vector retrieval combines Qdrant and rerank scores as `0.35 * vector_score + 0.65 * rerank_score` when rerank is available; otherwise it uses the clamped vector score.
- Tenant-fit local scoring uses source quality, near-term availability, price under `$35/SF`, scale above `15,000 SF`, and logistics terms such as loading dock, yard, and trailer storage.

### Missing Values, Conflicts, And No Results

Missing data is handled directly instead of being hidden behind a confident answer.

- Missing fields stay missing. Renderers say `unknown SF`, `unknown price`, or `availability unknown`; they do not infer values from similar listings.
- Data-quality questions route to a database report over critical fields: address, property type, square footage, rent, availability, market, coordinates, and source URL.
- Sources with chunks but no property rows are reported as context-only evidence. They can support source-text search, but they do not become structured facts until extraction can point at a real span.
- No-result structured queries call a relaxed matcher that removes numeric/date blockers and returns closest sourced rows when useful. The answer says which filters were applied and never fabricates a listing.
- Conflicting duplicate groups are answerable. Harbor Rd, for example, can explain why the fresher 62,000 SF correction outranks an older 58,000 SF inventory row while still citing the superseded source.
- Field-level receipts live in `property_field_values`, so a final answer can show not only the normalized value but also the raw value, method, confidence, source span, and extractor version.

### Hybrid Search And Vector Fallbacks

Hybrid search is conservative. Local lexical and fuzzy retrieval are the baseline; Qdrant can add semantic candidates when it is enabled, but Postgres still owns the source, property record, citation, and saved answer.

1. Query-time expansion reads [app/retrieval/retrieval_config.json](app/retrieval/retrieval_config.json). The source corpus is not mutated; the expanded terms live only on the query path and are recorded in `dependency_state_json`.
2. BM25S ranks the in-memory chunk corpus lexically. A standard-library substring retriever remains available as a simple fallback when exact configured terms are enough.
3. PolyFuzz edit distance handles typos, shorthand, partial names, and alias phrasing. TF-IDF character n-grams add another lightweight signal for noisy text overlap.
4. Optional Qdrant retrieval embeds `chunks.chunk_text` with `qwen3-embedding-0_6b-q8_0`, retrieves `cre_chunks`, and joins candidate chunk IDs back to Postgres. The existing `qwen3-reranker-0.6b` endpoint is exposed as a final rerank hook when vector search is enabled.
5. Candidate lists are merged with Reciprocal Rank Fusion, so each layer can keep its own scoring scale. Final evidence is deduped by `duplicate_group_key`, scored with relevance, authority, freshness, and matched feature coverage, then persisted exactly like structured evidence.
6. Loading-access search still requires concrete expanded-term hits in the chunk text. A broad semantic match without the expected source language does not become evidence.
7. `dependency_state_json` records layer status, contributors, query expansion terms, Qdrant/rerank usage, and disabled dependencies, so replay can explain why the answer looked the way it did.

That means exact structured answers still work when Qdrant is down, and source-text questions still get local BM25S/PolyFuzz/TF-IDF retrieval before any optional vector layer is considered.

### Instant Answers And Agent Mode

There are two names here, and they do different jobs. `instant_answer` is the delivery mode: the backend can answer now without waiting for Toolhouse. `route_mode` is the retrieval choice: `instant` means structured Postgres work, while `hybrid` means local chunk retrieval with lexical/fuzzy/vector signals. So a hybrid route can still produce an instant answer because it is still local and replayable.

The normal flow is predictable: route the question, retrieve evidence, render the answer, save the evidence, save the snapshot, and post the Slack reply with actions.

Agent mode starts only when the user clicks `Look deeper` or an operator runs the deeper-review path. The payload comes from `explain-query`: original question, local answer, route mode, reason codes, filters, allowed evidence IDs, evidence bundle, field details, and decision summary.

Toolhouse can write the second pass over that bundle, but it cannot bring in new facts on its own. The backend expects a structured response with status, rendered answer, cited evidence IDs, confidence label, reasoning summary, tools used, unsupported claims dropped, missing data, and suggested follow-ups. Unknown evidence IDs and unsupported tool names get rejected before the answer reaches Slack.

So the modes stay separate:

- `instant_answer`: fast, local, replayable delivery. It can use either structured retrieval or local hybrid retrieval.
- `instant` route mode: structured Postgres work for filters, aggregations, proximity, exact lookup, conflict explanation, and data quality.
- `hybrid` route mode: still local, but it can use chunk search, BM25S, PolyFuzz, TF-IDF, optional vector/rerank, and source-text evidence.
- `agent_mode`: Toolhouse-backed deeper review over an allowed evidence package, saved in `agent_runs`, with backend citation validation and local fallback behavior.

### Design Choices Worth Calling Out

- Postgres does two jobs: it stores the evidence and runs the queue. That keeps the operating model compact while still giving idempotency, retries, checkpoints, and replay.
- Slack appearances are separate from canonical documents. If someone shares the same file again, the app keeps the new Slack context without duplicating the facts.
- The app does not pretend it has a perfect master property table. It groups likely duplicates when answering, which makes conflicts easier to explain.
- LLM and Toolhouse work happen after retrieval. They can explain and compare evidence, but they cannot invent facts or cite IDs the backend did not allow.
- Missing data is visible. Data-quality answers and no-result explanations make the system's unknowns explicit.
- Degraded dependencies are visible too. Qdrant, rerank, OCR, Toolhouse, and local fallback states are recorded in health checks and answer snapshots.
- Verification tooling is part of the system, not an afterthought: golden evals, replay, readiness checks, secret scan, submission report, and the Graphify map all check that the app behaves the way this README says it does.

## The Slack Experience

A broker can ask:

| Slack prompt | What the agent demonstrates |
| --- | --- |
| `What properties do we have available near 123 Main Street?` | Proximity search over normalized property records with sourced nearby results. |
| `Show office buildings under $50/sq ft.` | Exact structured filtering that excludes higher-priced office inventory. |
| `Find listings that mention loading access or yard space.` | Hybrid retrieval over source text and field notes, with BM25S, PolyFuzz, TF-IDF, and optional Qdrant/rerank support. |
| `Why did you use 62k sq ft for Harbor Rd?` | Freshness and authority conflict handling with selected, supporting, and superseded evidence. |
| `Look deeper` | Toolhouse review over the allowed evidence bundle, with backend citation validation. |

Every factual answer includes a small source receipt: which route was used, how many evidence items were checked, and why those sources were selected. `Show sources` opens the rows, pages, files, and Slack messages behind the answer. `replay-query` rebuilds the stored answer outside Slack.

## Why It Is Credible

CRE data is full of small contradictions that matter. One spreadsheet says 58,000 SF. A later correction says 62,000 SF. A Slack thread explains why the newer value should win. This project treats that trail as the product.

The implementation favors plain reliability where facts matter:

- Slack is acknowledged quickly; slow parsing, indexing, answering, and Toolhouse calls run through background jobs.
- Live ingestion is conservative so generic chatter is not treated as evidence.
- Source appearances are stored separately from canonical documents, so repeated Slack shares keep their Slack context without duplicating facts.
- Golden evals verify routes, expected addresses, source labels, reason codes, evidence order, and dependency state.
- Agent runs persist Toolhouse/local deeper-review traces, raw responses, parsed payloads, citation validation, fallback state, and rendered output.

## Try It Locally

Local development uses Python 3.12 and `uv`.

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

For the live Slack environment used here:

- FastAPI app: `http://127.0.0.1:8020`
- Public callback: `https://slack.aqwerty321.me`
- Qdrant collection: `cre_chunks`
- Embeddings: `qwen3-embedding-0_6b-q8_0`
- Rerank: `qwen3-reranker-0.6b`
- OCR: GLM-OCR at `http://127.0.0.1:5003`
- Toolhouse Agent ID: `0c2c4555-5d96-47e4-8e05-f956de7a102e`

Use `.env.example` as the non-secret template. Local `.env` values are intentionally excluded from the source secret scan.

## Verification Commands

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
- [app/slack/](app/slack) owns Slack intake, answer rendering, source actions, and seed-data sync.
- [app/ingestion/](app/ingestion) handles sample import, Slack backfill, live ingestion, source receipts, and quality checks.
- [app/extraction/](app/extraction) parses native files and routes image/scanned-document OCR.
- [app/retrieval/](app/retrieval) and [app/routing/](app/routing) implement structured, hybrid, tenant-fit, and data-quality retrieval, including configurable aliases and retrieval weights in [app/retrieval/retrieval_config.json](app/retrieval/retrieval_config.json).
- [app/answering/query_service.py](app/answering/query_service.py) writes queries, evidence items, answer snapshots, and explanation payloads.
- [app/toolhouse/](app/toolhouse) contains the Workers API client, local deeper-review fallback, MCP server, backend tools, and citation validator.
- [app/evaluation/](app/evaluation) provides golden evals, replay, readiness checks (`demo-doctor`, `demo-dry-run`), secret scan, and submission report generation.
- [tests/](tests) covers golden answers, Slack loop behavior, ingestion, parsers, Toolhouse tools/client/MCP, and readiness commands.

## Submission Notes

- Recording script: [docs/slack-demo-video-script.md](docs/slack-demo-video-script.md)
- Slack runbook: [docs/slack-demo-runbook.md](docs/slack-demo-runbook.md)
- Sample data and evaluation plan: [docs/sample-data-and-evaluation.md](docs/sample-data-and-evaluation.md)
- Production practices and trade-offs: [docs/production-practices.md](docs/production-practices.md)
- Toolhouse readiness checkpoint: [docs/toolhouse-readiness-checkpoint.md](docs/toolhouse-readiness-checkpoint.md)
- Generated submission report: [.runtime/submission-report.md](.runtime/submission-report.md)

## Trade-offs And Next Steps

- The core implementation constraint is evidence continuity: Slack ingestion, document parsing, retrieval, citations, Slack actions, and Toolhouse review all operate on the same stored evidence IDs.
- The main architectural trade-off is a saved evidence trail plus Postgres-backed jobs instead of a heavier orchestration layer. That keeps replay, idempotency, retries, and source lineage straightforward in a CRE workflow where rent, square footage, and availability matter.
- The next production steps are OAuth and multi-workspace permissions, admin review for low-confidence extraction, object storage for files, telemetry dashboards, external geocoding and drive-time search, retrieval benchmark snapshots, and retention/deletion workflows for Slack-originated data.