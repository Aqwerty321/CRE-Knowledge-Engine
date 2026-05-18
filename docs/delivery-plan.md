# Delivery Plan

## Deadline

Submission is due May 20, 2026 with a GitHub repo link and demo video.

Current planning date: May 16, 2026.

## Execution Strategy

The project should optimize for a working, credible Slack demo, not production completeness. The architecture can point toward a larger system, but the implementation should keep the critical path narrow.

The council recommendation is to build the local evidence spine first, then expand into an ambitious live Slack demo:

```text
import_samples -> normalize -> retrieve -> answer_with_citations
```

After that passes, the target becomes:

```text
backfill_demo_channel -> ingest_new_file -> hybrid_search -> look_deeper
```

Use [production-practices.md](production-practices.md) to keep this plan priority-aware: P0 demo spine first, P1 live Slack trust loop second, P2 intelligence polish third, and two-week hardening last.

## Day-By-Day Plan

### May 16 - Lock Scope And Data

- Finalize docs and architecture decisions.
- Create sample data files from the manifest.
- Define database models and migrations.
- Implement or stub the local sample import contract.
- Seed coordinate lookup for proximity queries.
- Draft README sections and architecture diagram.

### May 17 - Build Ingestion And Extraction

- Scaffold FastAPI, Slack Bolt, worker, and PostgreSQL.
- Implement source document storage.
- Implement PostgreSQL-backed job polling before adding Redis/Celery.
- Implement PDF, CSV, XLSX, and text parsing.
- Implement normalization for address, property type, square footage, rent, and availability.
- Add bounded LLM extraction fallback for missed PDF/text fields if deterministic extraction leaves gaps.
- Add replayable extraction jobs.

### May 18 - Build Retrieval And Slack Answers

- Implement structured filters and aggregation.
- Implement chunking and keyword retrieval.
- Add Qdrant indexing for the hybrid golden query after structured golden queries pass.
- Implement query router with initial scores.
- Add source authority, freshness scoring, and answer-time duplicate grouping.
- Implement answer formatting and citations.
- Add Slack mention handler and threaded replies.
- Add `Show sources` action.
- Test golden queries against seeded data.

### May 19 - Toolhouse Escalation And Polish

- Expose backend retrieval tools for Toolhouse.
- Implement `Look deeper` action flow.
- Implement bounded live Slack backfill for the demo channel.
- Implement continuous new message/file ingestion.
- Add or polish checkpoints, retries, and rate-limit handling.
- Fill README setup/run instructions.
- Record a dry-run demo.

### May 20 - Final Demo And Submission

- Run final golden query pass.
- Record final Slack demo video.
- Verify README, architecture diagram, and sample query table.
- Push repo and prepare submission email.

## MVP Must-Haves

- Local sample import through Slack-shaped source records.
- Bounded live Slack channel backfill for at least one demo channel.
- New message/file ingestion.
- PDF, CSV, XLSX, and text parsing.
- Bounded LLM extraction fallback for missed fields.
- Structured property records with provenance.
- Chunk indexing with Qdrant for at least one hybrid query.
- Deterministic filters and aggregations.
- Proximity query using seeded coordinates.
- Source authority and freshness scoring.
- Answer-time duplicate grouping.
- Executable golden query checks.
- Slack answers with citations.
- Slack actions for `Show sources` and `Look deeper`.
- Toolhouse-powered deeper answer for at least one query.
- README and demo video.

## Stretch Goals

- Multi-channel configuration beyond the demo channel.
- `Broaden search` or `Retry with more context` Slack action.
- Route reason logs and retrieval score breakdowns.
- Lightweight ingestion status endpoint or CLI.
- More duplicate/conflict sample cases.

## Risk Register

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Slack permissions take longer than expected | Blocks live demo | Use one public demo channel and minimal scopes. |
| File download via Slack/Toolhouse is finicky | Blocks attachment parsing | Keep local sample data import command as fallback while preserving Slack metadata path. |
| Toolhouse integration takes time | Blocks agentic demo | Make deterministic backend work first; use Toolhouse only for one `Look deeper` flow. |
| Extraction quality is uneven | Bad answers | Use controlled sample files and field-level confidence. |
| Proximity geocoding is too much | Example query weak | Seed lat/lng in sample data and document external geocoding as future work. |
| Qdrant or embeddings slow local setup | Demo instability | Keep structured search fully functional and make semantic retrieval a separable layer. |
| Queue infrastructure grows too fast | Slows build | Use PostgreSQL-backed jobs first and add Redis only if needed. |

## Trade-Off Story

The core trade-off is deterministic reliability versus agent flexibility. The chosen architecture uses deterministic parsing, filtering, aggregation, and provenance for facts, then uses Toolhouse only when the user asks for deeper synthesis or the query is ambiguous.

This is a stronger take-home story than routing everything through an LLM because CRE users care about exact square footage, rent, availability, and source documents.

The second trade-off is reproducibility versus live integration. The project should ship a local sample import path that proves the full evidence model without Slack credentials, then show live Slack ingestion as the authentic product path when stable.

## Hardest-Part Story

The hardest part is not answering in natural language. It is keeping Slack ingestion, messy file extraction, structured facts, semantic retrieval, and citations aligned so the final answer is both useful and defensible.

## Two-More-Weeks Story

With two more weeks, improve:

- OCR and scanned brochure handling;
- external geocoding, radius search, and drive-time search;
- full canonical entity resolution and a property/source knowledge graph;
- admin/review UI for low-confidence extraction and failed files;
- analytics dashboard for missed questions, latency, escalation frequency, and retrieval quality;
- production multi-workspace and permission-aware ingestion;
- stronger reranking with retrieval snapshots and benchmark-driven tuning;
- richer Toolhouse workflows beyond evidence-grounded `Look deeper`.
