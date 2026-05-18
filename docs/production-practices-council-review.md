# Production Practices Council Review

## Question Framed For The Council

After drafting [production-practices.md](production-practices.md), the council reviewed whether it would actually prevent embarrassing implementation and demo mistakes for the Slack-native CRE Knowledge Engine.

The review focused on what to include, exclude, or update so the guide remains useful for the first build rather than becoming generic production theater.

## Where The Council Agrees

The evidence spine is still the central production practice. PostgreSQL facts, source documents, evidence items, citations, golden checks, and replayability matter more than broad infrastructure.

The draft correctly protects the highest-risk Slack paths: acknowledge quickly, queue slow work, dedupe retries, honor rate limits, follow cursors, and keep live Slack bounded to configured channels.

The LLM and Toolhouse boundaries are directionally right. LLMs can help with bounded extraction and wording, and Toolhouse can help with deeper synthesis, but neither should own facts, arithmetic, permission checks, or citations.

The doc needs priority labels. Without P0/P1/P2/defer language, future implementation could spend too much time on tracing, Qdrant aliases, or hardening before the local evidence spine is passing.

The demo should prove trust visibly. `Show sources`, answer snapshots, route labels, status output, conflict/freshness reasoning, and an explain-query path are low-effort polish that make the system feel serious.

## Where The Council Clashes

The council split on how much operational machinery belongs in the first version. The cautious view said OpenTelemetry, Qdrant blue/green aliases, and broad metrics should be deferred. The expansionist view said lightweight status and replay surfaces are demo multipliers. The resolution: structured logs, `make status`, `make demo-check`, and `make explain-query` are in; full telemetry and Qdrant alias rebuilds move to hardening.

The council split on Toolhouse breadth. The ambitious architecture lists six backend tools, but the executor view warned this can slow the first demo. The resolution: keep the six-tool target in the architecture, but the production guide emphasizes one evidence-bound `Look deeper` path and backend validation of Toolhouse evidence IDs.

The council split on field-level lineage. Making `property_field_values` mandatory may slow the first build, but claim-level trust requires raw value, normalized value, source span, method, confidence, and extractor version. The resolution: require that answer-rendered fields have equivalent lineage, whether stored in `property_field_values` or directly on records for the MVP.

## Blind Spots The Council Caught

The first draft did not clearly separate demo blockers from two-week production hardening.

The source lifecycle introduced statuses that drifted from the data dictionary. The final guide now keeps `source_documents.status` aligned with `pending`, `extracted`, `indexed`, `failed`, and `skipped`, while file download progress lives in jobs or metadata.

Slack event delivery records were missing from the schema. The data dictionary now includes `slack_events` so retry headers, event IDs, ignored channels, and delivery failures are auditable.

Answer replay was implied but not explicit. The data dictionary now includes `answer_snapshots`, and the production guide requires rendered answer text, evidence IDs, dependency state, and model/prompt versions when used.

The first draft trusted Toolhouse too much. The final guide requires backend validation that Toolhouse citations map to allowed evidence IDs before Slack posting.

The demo needed a trust receipt: route label, concise answer, sources, reason used, query ID, evidence count, and replay path.

## The Recommendation

Keep [production-practices.md](production-practices.md) as the main build guardrail, but make it executable and priority-aware.

The final update should include:

- P0/P1/P2/defer priority legend;
- first build execution path;
- trust invariants for claim-to-evidence coverage;
- recording-day fallback contract;
- configured-channel allowlist rules;
- Slack event delivery storage;
- answer snapshots for replayability;
- field lineage expectations for answer-rendered facts;
- Toolhouse evidence-ID validation;
- concrete `make status`, `make demo-check`, and `make explain-query` output contracts;
- operator runbook for the demo path;
- demo trust receipt checklist;
- pre-recording secret hygiene.

Defer full telemetry dashboards, Qdrant alias rebuilds, OAuth install flow, multi-workspace production permissions, object storage, OCR, external geocoding, admin UI, and full entity resolution to the two-week story.

## The One Thing To Do First

Build and keep green the P0 local evidence spine:

```text
make dev-up -> make migrate -> make import-samples -> make golden
```

The first implementation win is not live Slack or Toolhouse. It is proving that a local Slack-shaped source can become normalized facts, cited answers, evidence items, and replayable answer snapshots. Everything impressive should layer on top of that.
