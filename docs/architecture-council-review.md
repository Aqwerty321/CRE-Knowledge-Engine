# Architecture Council Review

This review established the evidence spine and risk-control posture. The later scope rebalance in [ambitious-scope-council-review.md](ambitious-scope-council-review.md) expands the build-now list after the user clarified there is enough time and AI assistance for higher-leverage additions. Treat the scope rebalance as the current build target when the two reviews differ.

## Question Framed For The Council

The project is a Slack-native CRE knowledge agent take-home due May 20, 2026. The current docs describe a backend-owned retrieval system with Slack Bolt, PostgreSQL, Qdrant, deterministic extraction, sourced answers, and one Toolhouse escalation path.

The council debated these high-leverage decisions:

- Slack Bolt backend ownership versus Toolhouse-first ownership;
- PostgreSQL plus Qdrant versus PostgreSQL-only or pgvector;
- Redis/Celery/RQ versus a PostgreSQL-backed job table;
- live Slack backfill first versus local sample import first;
- deterministic extraction versus LLM extraction fallback;
- broad Toolhouse orchestration versus one focused MVP escalation.

## Where The Council Agrees

The backend should own truth. Slack events, ingestion, extraction, storage, deterministic retrieval, citations, and answer logs belong in code we control. Toolhouse should not be the system of record for CRE facts.

PostgreSQL is the mandatory spine. It should store source documents, property records, chunks metadata, queries, evidence, and ingestion jobs. All other systems are adapters or indexes.

Local sample import should come before live Slack backfill. It is not a fake path if it writes the same `source_documents`, `property_records`, `chunks`, and evidence tables that Slack backfill writes. It protects the demo from Slack permissions, file download, rate-limit, and cursor issues.

The queue should start as a PostgreSQL-backed `ingestion_jobs` table plus a worker loop. Slack requires fast acknowledgement and durable follow-up work, but the demo does not require Redis, Celery, or RQ unless implementation speed demands them.

Deterministic extraction should own CRE facts and arithmetic. LLMs can help recover candidate fields or synthesize recommendations, but they should not invent rent, square footage, availability, addresses, or source citations.

Toolhouse should be visible but narrow. One polished `Look deeper` flow over backend evidence is more convincing than several thin agent workflows.

## Where The Council Clashes

The main disagreement was Qdrant. The expansionist view favored Qdrant because it cleanly demonstrates a structured-plus-semantic architecture. The contrarian and outsider views warned that Qdrant is another service, sync path, and demo failure point for only 8 to 10 sample files.

The compromise: keep Qdrant in the intended architecture and require it for one or two hybrid demo queries, such as loading access or yard space. It must not be required for exact lookup, filters, aggregation, proximity, or citations.

The second disagreement was LLM extraction. A constrained fallback can help messy PDFs or text, but it can also blur trust boundaries. The compromise: deterministic and heuristic extraction first; schema-bound extraction only when a parser misses fields, with source snippets and confidence attached.

The third disagreement was how much Toolhouse should appear. Toolhouse-first may sound more aligned with the prompt, but it weakens provenance. Backend-first may sound under-Toolhouse unless the demo shows a real agentic escalation. The compromise: make `Look deeper` part of the golden path.

## Blind Spots The Council Caught

The current docs were directionally strong but still too wide for the remaining schedule. Slack Bolt, Toolhouse, PostgreSQL, Qdrant, worker queue, file downloads, PDF/CSV/XLSX parsing, routing, citations, buttons, backfill, and a video are all independent places the demo can fail.

The MVP needed a clearer fallback contract. A local importer is not just mitigation; it is the reproducible evaluation harness the repo can ship with.

The queue decision was under-specified. The docs mentioned queues and Redis only conditionally, but the data dictionary already has enough shape for database-backed jobs.

The extraction boundary needed sharpening. `semantic` extraction should mean a bounded, provenance-bearing fallback, not open-ended fact generation.

The Toolhouse surface was slightly too broad. Six backend tools are useful later, but the MVP likely only needs `search_properties`, `search_source_chunks`, and `get_source_detail`, plus an evidence bundle handoff.

The sample PDFs should be generated from real text, not image scans. OCR is a future improvement and should not sneak into the critical path.

## The Recommendation

Build the MVP around a deterministic evidence spine:

1. Local sample import writes Slack-shaped source documents and files.
2. PostgreSQL stores source documents, property records, chunks metadata, ingestion jobs, queries, and evidence.
3. A simple worker loop processes database jobs and preserves checkpoints.
4. Deterministic parsers and normalizers produce CRE facts with provenance.
5. Structured retrieval answers exact lookup, filters, aggregation, and seeded proximity.
6. Slack Bolt posts concise sourced answers and source views.
7. Qdrant powers at least one hybrid query, while structured answers remain independent.
8. Toolhouse powers one `Look deeper` synthesis over backend evidence.
9. Live Slack backfill lands after the local golden path works.

Decision table:

| Decision | Pick | Why |
| --- | --- | --- |
| Slack ownership | Slack Bolt backend | Fast acknowledgement, idempotency, provenance, and deterministic replies. |
| Toolhouse ownership | Escalation only | Demonstrates agentic value without making facts opaque. |
| Primary store | PostgreSQL | Best source of truth for records, evidence, jobs, filters, and replay. |
| Vector layer | Qdrant targeted for hybrid retrieval | Required for the hybrid demo path, but not for structured demo queries. |
| Queue | PostgreSQL-backed jobs first | Durable enough for the demo with fewer moving parts. |
| Ingestion sequence | Local import first, Slack backfill second | Keeps the demo reproducible and de-risks Slack setup. |
| Extraction | Deterministic and heuristic first | CRE facts need exactness and source traceability. |
| LLM use | Bounded extraction fallback and synthesis over evidence | Helpful where ambiguity exists, unsafe as primary truth. |
| Toolhouse MVP | One `Look deeper` path | Highest signal with lowest scope. |

## The One Thing To Do First

Create the local sample import and golden query loop before full Slack backfill, Qdrant, or Toolhouse.

The first milestone should be:

```text
import_samples -> normalize -> retrieve -> answer_with_citations
```

Once that works, Slack, Qdrant, and Toolhouse become adapters over a proven evidence spine instead of risky foundations.
