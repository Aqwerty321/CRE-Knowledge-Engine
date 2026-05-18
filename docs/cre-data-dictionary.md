# CRE Data Dictionary

## Design Goals

The data model must support three things at the same time:

- structured CRE facts for filters and aggregation;
- unstructured evidence for semantic retrieval;
- provenance strong enough to cite original Slack sources.

## Core Entities

### `source_documents`

Represents a Slack message, thread reply, PDF, CSV, XLSX, or text file.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `source_type` | enum | `slack_message`, `slack_thread_reply`, `pdf`, `csv`, `xlsx`, `text`. |
| `slack_team_id` | text | Workspace ID. |
| `slack_channel_id` | text | Channel ID. |
| `slack_channel_name` | text | Cached for display. |
| `slack_user_id` | text | Sender or uploader. |
| `slack_user_name` | text | Cached for display. |
| `slack_ts` | text | Message timestamp when applicable. |
| `slack_thread_ts` | text | Parent timestamp when applicable. |
| `slack_file_id` | text | File ID when applicable. |
| `file_name` | text | Original filename. |
| `file_mime_type` | text | MIME type from Slack. |
| `source_url` | text | Slack permalink or file URL. |
| `local_path` | text | Local stored copy or object key. |
| `raw_text` | text | Extracted full text when available. |
| `raw_payload_hash` | text | Dedupe and replay. |
| `content_hash` | text | Dedupe repeated files. |
| `posted_at` | timestamptz | Source creation time. |
| `ingested_at` | timestamptz | Backend intake time. |
| `status` | enum | `pending`, `extracted`, `indexed`, `failed`, `skipped`. |
| `error_message` | text | Last failure reason. |

Recommended unique constraints:

- `(slack_team_id, slack_channel_id, slack_ts)` for messages;
- `(slack_team_id, slack_file_id)` for files;
- `content_hash` for repeated uploaded content when safe.

### `chunks`

Represents retrieval-ready text.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `document_id` | UUID | References `source_documents`. |
| `chunk_index` | integer | Stable order in document. |
| `chunk_text` | text | Text sent to embedding/search. |
| `page_number` | integer | PDF page when available. |
| `row_number` | integer | CSV/XLSX row when available. |
| `section_name` | text | Optional heading or sheet name. |
| `embedding_id` | text | Qdrant point ID. |
| `token_count` | integer | Approximate chunk size. |
| `metadata_json` | jsonb | Channel, file, property hints, extraction method. |

### `property_records`

Represents normalized CRE facts extracted from one source.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `document_id` | UUID | Source document. |
| `chunk_id` | UUID | Best supporting chunk if available. |
| `address` | text | Display address as extracted. |
| `normalized_address` | text | Canonical comparison value. |
| `property_type` | enum | `office`, `industrial`, `retail`, `mixed_use`, `land`, `multifamily`, `unknown`. |
| `sq_ft` | integer | Whole square feet. |
| `price_per_sq_ft` | numeric | Asking rent or price per square foot. |
| `price_basis` | enum | `annual_rent`, `monthly_rent`, `sale_price`, `unknown`. |
| `availability` | text | Display label. |
| `availability_date` | date | Normalized date when known. |
| `market` | text | Market or submarket. |
| `geo_lat` | numeric | Seeded or geocoded latitude. |
| `geo_lng` | numeric | Seeded or geocoded longitude. |
| `source_page` | integer | PDF page. |
| `source_row` | integer | CSV/XLSX row. |
| `extraction_method` | enum | `deterministic`, `heuristic`, `semantic`, `manual_seed`. |
| `confidence` | numeric | 0.0 to 1.0. |
| `source_authority_score` | numeric | Lightweight source reliability score for ranking. |
| `freshness_score` | numeric | Recency score for ranking. |
| `duplicate_group_key` | text | Optional answer-time grouping key from normalized address/type. |
| `created_at` | timestamptz | Record creation. |
| `updated_at` | timestamptz | Last update. |

### `property_field_values`

Optional but useful for field-level confidence.

This table is not required for the first golden demo if source-level confidence on `property_records` is enough. Add it when field-level uncertainty becomes useful for extraction debugging or answer ranking. Any field rendered in a final answer should be traceable to equivalent raw value, normalized value, method, confidence, and source-span metadata, whether stored here or directly on the property record.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `property_record_id` | UUID | References `property_records`. |
| `field_name` | text | Example: `sq_ft`, `price_per_sq_ft`. |
| `raw_value` | text | Original value. |
| `normalized_value` | text | Normalized value. |
| `confidence` | numeric | Field-level confidence. |
| `method` | enum | `deterministic`, `heuristic`, `semantic`, `manual_seed`. |
| `source_span` | text | Snippet, page span, row cell, or Slack text span supporting the value. |
| `extractor_version` | text | Parser, rule, prompt, or model version that produced the value. |

### `slack_events`

Records Slack deliveries separately from source documents so retries, idempotency, and debugging are explicit.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `slack_event_id` | text | Top-level Slack Events API event ID when present. |
| `slack_team_id` | text | Workspace/team ID. |
| `slack_channel_id` | text | Channel ID if present. |
| `event_type` | text | Outer or inner Slack event/action type. |
| `retry_num` | integer | `x-slack-retry-num` when present. |
| `retry_reason` | text | `x-slack-retry-reason` when present. |
| `payload_hash` | text | Hash of stored or received payload for replay/dedupe. |
| `status` | enum | `received`, `ignored`, `queued`, `processed`, `failed`. |
| `error_code` | text | Stable internal error code when handling fails. |
| `received_at` | timestamptz | Delivery receipt time. |
| `processed_at` | timestamptz | Completion time when applicable. |

Recommended unique constraints:

- `(slack_team_id, slack_event_id)` for Events API callbacks when `slack_event_id` exists;
- `(payload_hash, received_at)` only as a debugging aid, not primary dedupe.

### `queries`

Records user questions and route decisions.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `slack_channel_id` | text | Query location. |
| `slack_user_id` | text | User who asked. |
| `slack_ts` | text | Query message timestamp. |
| `query_text` | text | User question. |
| `route_mode` | enum | `instant`, `hybrid`, `agentic`, `failed`. |
| `route_confidence` | numeric | 0.0 to 1.0. |
| `reason_codes` | text[] | Example: `numeric_filter`, `aggregation`, `ambiguous`. |
| `created_at` | timestamptz | Query time. |

### `evidence_items`

Connects answers to the facts and chunks used.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `query_id` | UUID | References `queries`. |
| `document_id` | UUID | Source document. |
| `chunk_id` | UUID | Supporting chunk. |
| `property_record_id` | UUID | Supporting property record. |
| `relevance_score` | numeric | Retrieval or ranking score. |
| `matched_fields` | text[] | Fields that matched. |
| `source_summary` | text | Short display citation. |

Evidence items should be stable enough to pass to Toolhouse. The agent should receive evidence IDs and source summaries, not free-floating facts.

### `answer_snapshots`

Stores replayable final-answer state for trust, debugging, and `Show sources` / `explain-query` behavior.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `query_id` | UUID | References `queries`. |
| `rendered_answer` | text | Exact Slack-visible answer text. |
| `route_mode` | enum | Copied from route decision at answer time. |
| `filters_json` | jsonb | Structured filters or relaxed filters used. |
| `evidence_ids` | UUID[] | Evidence items included in the rendered answer. |
| `dependency_state_json` | jsonb | Qdrant, Toolhouse, LLM, and fallback state. |
| `model_versions_json` | jsonb | Model, prompt, or embedding versions used when applicable. |
| `created_at` | timestamptz | Answer creation time. |

### `ingestion_jobs`

Tracks replayable work.

| Field | Type | Notes |
| --- | --- | --- |
| `id` | UUID | Internal primary key. |
| `job_type` | enum | `backfill`, `file_download`, `extract`, `index`, `reindex`. |
| `source_document_id` | UUID | Optional source. |
| `status` | enum | `queued`, `running`, `succeeded`, `failed`, `retrying`. |
| `attempt_count` | integer | Retry tracking. |
| `checkpoint_json` | jsonb | Cursor, page, or timestamp progress. |
| `error_message` | text | Last failure reason. |

For the MVP, this table is also the queue. A worker can poll and claim jobs from PostgreSQL before Redis, RQ, or Celery are introduced.

Minimum indexes:

- `(status, job_type, created_at)` for worker polling;
- `(source_document_id, job_type)` for idempotent retries;
- `(status, updated_at)` for stuck-job recovery.

## Normalization Rules

### Address

- Preserve original display value.
- Normalize case, punctuation, common suffixes, and whitespace.
- Do not invent missing unit numbers.
- For MVP proximity, join against a seeded address coordinate table.

### Property Type

Canonical values:

- `office`;
- `industrial`;
- `retail`;
- `mixed_use`;
- `land`;
- `multifamily`;
- `unknown`.

Examples:

- `Class A Office`, `creative office`, and `medical office` map to `office` with raw subtype preserved in metadata.
- `warehouse`, `flex`, `distribution`, and `light industrial` map to `industrial`.

### Square Footage

- Store as integer square feet.
- Accept `SF`, `sq ft`, `sqft`, `RSF`, `rentable square feet`, and compact values such as `4.8k SF`.
- Do not combine multiple suites unless the document clearly states total available area.

### Price Per Square Foot

- Store numeric `price_per_sq_ft`.
- Preserve `price_basis` because sale price and rent are not interchangeable.
- Treat missing basis as `unknown`; do not assume annual rent unless the sample format or column header states it.

### Availability

- Preserve raw label.
- Normalize direct dates when available.
- Map `available now`, `immediate`, and `vacant` to the current demo date if date math is needed, while keeping display label intact.
- Normalize quarter labels such as `Q3 2026` to a representative date only for sorting, not for exact claims.

## Deduplication Rules

Start simple:

- Slack message duplicates: `(team, channel, ts)`.
- Slack file duplicates: `(team, file_id)`.
- Content duplicates: `content_hash`.
- Property duplicates: compare normalized address, property type, and overlapping source date.

Do not fully merge duplicate properties in the MVP. Instead, group likely duplicates at answer time and cite the freshest or most authoritative source first.

The ambitious MVP should include answer-time duplicate grouping. Full canonical entity resolution remains future scope.

## Source Authority MVP

Use simple weights in ranking:

| Source | Suggested Weight |
| --- | --- |
| CSV/XLSX inventory | High |
| PDF flyer | Medium-high |
| Slack message by teammate | Medium |
| Older duplicate source | Lower |
| Low-confidence semantic extraction | Lower |

Authority should influence ranking, not erase conflicting evidence.

Freshness should also influence ranking. A newer explicit correction can outrank an older flyer or inventory row, but the answer should cite both when the conflict matters.

## Bounded LLM Extraction Fallback

LLM extraction is allowed only as a recovery layer.

Rules:

- run deterministic and heuristic extraction first;
- pass only the source text, page, row, or chunk being inspected;
- request a fixed JSON schema for candidate fields;
- store raw supporting snippet, confidence, and extraction method;
- never let the LLM compute totals, averages, filters, or distances;
- never use an extracted field in an answer without provenance.

## Provenance Rule

Every normalized fact must point back to a `source_document` and, when possible, a page, row, or chunk. A fact without provenance should not be used in a final answer.

## Import Contract

Local sample import and live Slack backfill must produce the same records. The importer should populate Slack-shaped values such as channel, user, timestamp, file name, and source URL even when the data originated from local sample files.

This makes local golden-query verification meaningful and keeps Slack integration as an adapter over the same evidence model.
