# Ambitious Scope Council Review

## Question Framed For The Council

The previous architecture review tightened the MVP around a local evidence spine. The user pushed back that this was too constrained: they have more time, an AI assistant, and want to include more high-leverage features that require moderate extra effort.

The council re-evaluated what should move into the build plan now versus what should remain the follow-up-call answer to: what would you change if you had two more weeks?

Candidate features:

- bounded live Slack backfill;
- continuous message and file ingestion;
- Qdrant-backed hybrid search;
- richer Toolhouse backend tools;
- bounded LLM extraction fallback;
- source authority and freshness scoring;
- duplicate grouping;
- executable golden query tests;
- richer Slack actions;
- multi-channel configuration;
- seeded geocoding and proximity;
- OCR and image handling;
- reranking;
- admin/review UI;
- analytics;
- knowledge graph and entity resolution.

## Where The Council Agrees

The original evidence spine is still right, but it should be used as a guardrail rather than a ceiling.

Build now should include a real Slack loop, not only a local importer. The local importer remains the reproducible test harness, but the demo should show one configured Slack channel being backfilled and receiving new messages or files.

The trust layer deserves more ambition. Source authority, freshness scoring, duplicate grouping, source display, and golden query tests are moderate-effort features that make the system feel CRE-aware rather than generic.

Qdrant should be part of the full demo path. Exact structured answers should still work without Qdrant, but at least one golden query should depend on semantic retrieval so the hybrid architecture is visible.

Toolhouse should get a richer but still boring tool surface. The agent should be able to search properties, aggregate structured facts, search source chunks, inspect source detail, run nearby-property lookup, and explain evidence. Toolhouse still must not own canonical facts.

Bounded LLM extraction fallback is worth including if it is schema-bound and source-backed. It should only recover candidate fields when deterministic extraction misses, and it must not perform arithmetic or cite unsupported facts.

## Where The Council Clashes

The council split on how strong to make Qdrant. The bolder view says Qdrant should be required for the full demo because hybrid retrieval is part of the product claim. The cautious view says structured answers should not depend on it. The resolution: Qdrant is required for the hybrid golden query, but PostgreSQL remains the source of truth and structured fallback.

The council split on live Slack breadth. The bolder view says full backfill is a hard assignment requirement. The cautious view warns against broad workspace coverage. The resolution: implement one to three configured channels with history, threads, files, checkpoints, and rate-limit handling. Do not build enterprise-wide administration.

The council split on multi-channel configuration. The resolution: support a simple environment or database list of configured channels, but demo one polished channel.

The council split on Toolhouse breadth. The resolution: expose the full six-tool backend surface if feasible, but keep the visible demo centered on `Look deeper`, source inspection, and evidence-grounded recommendation.

## Blind Spots The Council Caught

Golden query tests are not just engineering hygiene. They are the fastest way to prove that the architecture works and to keep the bigger scope from drifting.

Freshness and duplicate behavior are demo multipliers. A correction such as Harbor Rd changing from 58k to 62k square feet can demonstrate that the system understands source authority and recency, not just text similarity.

Slack actions have unusually high product leverage. `Show sources`, `Look deeper`, message updates, and optionally `Broaden search` make the bot feel like a real teammate while reusing existing backend logic.

OCR, admin UI, analytics dashboards, external geocoding, and full entity resolution are tempting but would create new product surfaces or high-variance parsing problems. They are better as the two-week future story.

## The Recommendation

Upgrade the target from a conservative MVP to an ambitious evidence-first Slack demo.

Build now:

| Feature | Scope |
| --- | --- |
| Local sample import | Reproducible harness writing the same records as Slack ingestion. |
| Live Slack backfill | One to three configured channels with history, thread replies, files, checkpoints, and idempotency. |
| Continuous ingestion | New messages and file uploads enqueue through the same job system. |
| PostgreSQL evidence spine | Sources, chunks metadata, property records, evidence, queries, and jobs. |
| Qdrant hybrid retrieval | Required for at least one semantic golden query, with keyword fallback. |
| Deterministic extraction | PDF, CSV, XLSX, text, and Slack message extraction for core facts. |
| Bounded LLM extraction fallback | Schema-bound candidate extraction with source snippet, confidence, and method. |
| Source authority and freshness | Lightweight weights by source type and recency. |
| Duplicate grouping | Answer-time grouping by normalized address, property type, and recency. |
| Golden query tests | Executable checks for the sample query set. |
| Slack UX | Threaded replies, message updates, `Show sources`, `Look deeper`, and optionally `Broaden search`. |
| Toolhouse tools | `search_properties`, `aggregate_properties`, `search_source_chunks`, `get_source_detail`, `nearby_properties`, `explain_evidence`. |
| Seeded proximity | Fixed address coordinates and Haversine distance. |
| Lightweight status | Logs, route records, and optional ingestion status endpoint or CLI. |

Build if time:

- multi-channel configuration beyond the demo channel;
- richer source previews with Slack permalinks, page, row, sender, timestamp, and matched value;
- `Broaden search` or `Retry with more context` button;
- route reason logs and retrieval score breakdowns;
- additional conflict and duplicate sample cases.

Keep for the two-week follow-up answer:

- OCR and image-only brochure extraction;
- external geocoding, radius search, and drive-time search;
- full canonical entity resolution and knowledge graph over properties, brokers, tenants, markets, and sources;
- admin/review UI for low-confidence extraction and failed files;
- analytics dashboard for missed questions, latency, escalation frequency, and retrieval quality;
- production multi-workspace permission model;
- stronger reranking, retrieval snapshots, and benchmark-driven tuning;
- richer Toolhouse workflows beyond evidence-grounded `Look deeper`.

## The One Thing To Do First

Keep the first milestone the same, but treat it as a test harness, not the final scope:

```text
import_samples -> normalize -> retrieve -> answer_with_citations
```

Once that passes, immediately expand into the real Slack evidence loop:

```text
backfill_demo_channel -> ingest_new_file -> hybrid_search -> look_deeper
```

That is the balanced target: bolder in the demo, still disciplined in the architecture.
