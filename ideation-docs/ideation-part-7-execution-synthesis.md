# Ideation Part 7 - Execution Synthesis

## Purpose

The first six ideation documents establish a strong product philosophy: a calm, retrieval-native CRE intelligence layer that uses deterministic systems first and escalates only when ambiguity justifies deeper reasoning.

This document turns that philosophy into execution decisions for the May 20, 2026 take-home deadline.

## Consolidated Product Thesis

Build a Slack agent that behaves like a precise CRE analyst over team knowledge:

- it ingests Slack messages, threads, and files;
- it extracts structured property facts and preserves source provenance;
- it stores both structured records and semantic chunks;
- it answers obvious factual questions without model theater;
- it escalates ambiguous or synthesis-heavy questions into a Toolhouse-powered agent path;
- it always cites where the answer came from.

The product should feel useful before it feels impressive.

## Decisions That Are Now Fixed

### Backend Owns Knowledge

Toolhouse should not be the primary database or retrieval engine. The backend owns ingestion, parsing, normalization, indexing, retrieval, ranking, citations, and audit logs.

Toolhouse owns the agentic layer: Slack-facing worker behavior, deeper synthesis, and tool orchestration when the query needs more than deterministic retrieval.

### Slack Events Are Acknowledged Fast

Slack event handlers must acknowledge quickly and enqueue work. Parsing files, downloading historical data, embedding chunks, and agentic synthesis should not block event acknowledgement.

### MVP Includes Minimal Proximity

The assignment example asks for properties near an address, so proximity cannot be treated only as a future feature. The prototype should include deterministic distance search using lat/lng already present in sample data and a tiny seeded address lookup table.

External geocoding is a stretch goal.

### XLSX Is In Scope

The assignment explicitly names Excel files. The MVP should parse at least one `.xlsx` sample through `pandas` plus `openpyxl`, even if the initial extraction rules are simple.

### Sources Are A Product Feature

Every answer should preserve enough lineage to answer: where did that come from?

Minimum citation fields:

- Slack channel and timestamp;
- sender or uploader;
- file name or message text source;
- page, row, or chunk when available;
- Slack permalink or file URL when available.

### Scope Needs A Hard Boundary

The first six ideation docs include future-grade ideas: truth hierarchy, capability registry, advanced degradation, entity identity, knowledge graph, OCR, human review, and retrieval snapshots.

For the take-home, these should appear as architecture-aware future work, not required MVP implementation.

## MVP Definition

The prototype is successful if it can do the following reliably in Slack:

1. Backfill a configured channel for messages, files, and thread roots.
2. Ingest new messages and file events after startup.
3. Parse PDFs, CSVs, XLSX files, and text messages from sample data.
4. Extract property records with address, type, square footage, price per square foot, availability, source, and confidence.
5. Index text chunks for semantic retrieval.
6. Answer direct factual questions using structured data.
7. Answer fuzzy questions using hybrid structured plus semantic retrieval.
8. Answer at least one synthesis-heavy query through the Toolhouse escalation path.
9. Include sources in every answer.
10. Show a clean demo with sample data and expected answers.

## Deferred But Named

These remain strong follow-up-call answers, but should not distract from the prototype:

- OCR for scanned PDFs and image-only files;
- external geocoding and drive-time search;
- sophisticated entity resolution across properties;
- source authority scoring beyond simple recency and document type weights;
- full capability registry and adaptive thresholds;
- human review UI for uncertain extraction;
- analytics dashboards and retrieval benchmarks;
- durable conversational memory beyond the active Slack thread.

## Implementation Shape

Use a Python modular monolith with clear internal boundaries:

```text
app/
  api/
  slack/
  ingestion/
  extraction/
  normalization/
  indexing/
  retrieval/
  routing/
  answering/
  toolhouse/
  db/
  models/
  workers/
```

Run locally with Docker Compose:

- `api` - FastAPI plus Slack Bolt receiver;
- `worker` - ingestion, parsing, indexing, and backfill jobs;
- `postgres` - structured data and provenance;
- `qdrant` - semantic chunks;
- `redis` - only if the worker queue needs it.

## Demo Narrative

The video should tell a simple story:

1. A sample CRE channel contains messages and files.
2. The bot backfills or ingests them.
3. A direct query returns a fast, sourced answer.
4. A numeric filter or aggregation returns exact results.
5. A proximity query works from seeded coordinates.
6. A fuzzy or synthesis query uses the deeper Toolhouse path.
7. Sources can be inspected without cluttering the channel.

## Final Principle

Use deterministic systems whenever possible. Escalate intelligence only when uncertainty justifies it. Preserve provenance always.
