# Pre-Agent Mode Audit And Next-Level Ideas

## Purpose

This is the current implementation audit before starting smart agent mode.

The goal is to be honest about what is already strong, identify the gaps that can make Toolhouse or agent mode feel brittle, and preserve a set of higher-leverage product ideas for the Slack experience.

## Graphify Snapshot

Graphify was rebuilt on 2026-05-19 with the repo-local command:

```bash
./.opencode/scripts/build-graphify
```

The graph was refreshed again after the hybrid retrieval, expanded corpus, and live Slack workflow pass. The latest report is:

- 767 nodes;
- 1345 edges;
- 56 communities.

The graph's highest-signal hubs now match the real implementation, not just the planning docs:

- `LocalHybridRetrievalPipeline`, `RetrievalDocument`, and `RetrievalHit` for the lexical/fuzzy/vector retrieval stack;
- `import_sample_dataset()` for the source/evidence ingestion spine;
- `answer_query()` and `explain_query()` for answer orchestration and trust receipts;
- `build_live_demo_datasets()` and `_build_live_file_matches()` for live Slack metadata sync, including title/name file matching;
- `enqueue_slack_ingestion_event()` and `ingest_slack_file_checkpoint()` for live Slack message/file ingestion;
- `parse_source_file()` for native PDF/XLSX/CSV/text parsing;
- `SlackPersonaSeeder` and `SlackFileSeeder` for live workspace preparation;
- `process_pending_query_jobs()` and `run_query_worker_loop()` for the Slack answer loop;
- `build_answer_blocks()` and `get_slack_app()` for the current Slack interface boundary.

Graphify also highlighted a useful warning: the worker/runtime and Slack action communities are still thin. That is expected because they were implemented recently, but it also points to where the next integration risk sits.

## Current Progress

### Evidence Spine

Implemented and validated:

- manifest-driven source import;
- `source_documents`, chunks, property records, field values, queries, evidence items, and answer snapshots;
- deterministic structured queries;
- hybrid keyword-backed conflict and chunk retrieval;
- explanation payloads that replay route, filters, answer snapshot, evidence, chunks, and field details;
- live Slack metadata overlay for seeded files and persona messages.

Current database status from `uv run cre-cli status`:

- 23 source documents;
- 23 chunks;
- 25 property records;
- 225 property field values;
- database reachable;
- configured Slack channel IDs present.

### Slack Workspace And Demo Prep

Implemented and live-verified:

- persona seeding with customized Slack bot username/avatar mode;
- file seeding with Slack `files_upload_v2`;
- live Slack demo source sync with real Slack file IDs, message timestamps, channel names, and permalinks;
- seeded channels for listings, market research, private demo context, and agent Q and A;
- recording script, persona sheet, and runbook.

### Slack Answer Loop

Implemented and validated:

- Slack Bolt HTTP request endpoints;
- `app_mention` intake;
- retry-aware event dedupe;
- configured-channel allowlist;
- `answer_query` job enqueueing;
- lifespan-managed background worker;
- threaded answer posting;
- `Show sources` button;
- `Show sources` ephemeral trust receipt.

The live runtime worker was verified by posting a signed Slack event into the real local app endpoint and confirming that a threaded answer appeared in Slack without manually calling the job processor.

### Test State

Current full-suite validation:

```bash
uv run pytest -q
```

Current result: 100 passed.

Result:

- 97 tests pass after the Slack UX hardening, source-receipt/table support, live Toolhouse smoke slice, native parser fixtures, Slack ingestion pass, source-post receipt trail, agent-run persistence, golden eval harness, query replay pass, demo dry run, secret scan, expanded corpus battery, and submission report pass;
- no known failures or warning noise remain.

Post-hardening additions:

- broad heuristic query-constructor parsing;
- generic structured property search, exact lookup, aggregation, data-quality, and tenant-fit answers;
- missing-data explanations for no-result structured queries;
- local `Look deeper` with evidence ID validation;
- deterministic Toolhouse-facing tool functions;
- `/health/deps` job-count visibility.

## What Is Ready For Smart Agent Mode

The foundation is ready enough for a narrow smart-agent slice because:

- answers are already grounded in stored evidence;
- evidence can be replayed through `explain_query`;
- Slack can receive a question and post the answer automatically;
- the demo workspace now contains real Slack-visible source material;
- live Slack permalinks are attached to the evidence model;
- the agent can be framed as a deeper synthesis layer over trusted retrieval, not as the fact source.

## Remaining Gaps Before Smart Agent Mode

### P0: Build The Agent Boundary

`app/toolhouse/` is still empty.

Before any real smart-agent behavior, add a thin boundary that can:

- accept a prior `query_id`;
- load the stored answer and evidence bundle;
- package only allowed evidence IDs, source summaries, snippets, and source URLs;
- return a bounded synthesis payload;
- mark whether the result is Toolhouse-backed, local-stubbed, or unavailable.

The first implementation should be boring and strict. It should not let the agent browse or invent property facts outside the evidence package.

### P0: Add `Look deeper`

The current Slack answer block only offers `Show sources`.

Smart agent mode needs a visible escalation action:

- add a `Look deeper` button next to `Show sources`;
- register a `look_deeper` Slack action;
- post an immediate acknowledgment such as `On it. Checking the messy bits.`;
- run the deeper path as a job;
- post the final deeper answer in the same thread.

The first version can be local and evidence-bound before Toolhouse credentials are connected.

### P0: Validate Agent Citations

The agent output must be checked against the evidence bundle before Slack sees it.

Minimum validator:

- every cited source ID must come from the allowed evidence IDs;
- every source summary must map to a stored `EvidenceItem` or `SourceDocument`;
- unsupported claims must be dropped or rewritten as uncertainty;
- if validation fails, the Slack answer should downgrade to a safe fallback.

This is the trust invariant that keeps smart mode from undermining the deterministic spine.

### P1: Create A Minimal Backend Tool Surface

The first Toolhouse-facing tools should be small and deterministic:

- `explain_evidence(query_id)`;
- `search_properties(filters)`;
- `search_source_chunks(query, filters)`;
- `get_source_detail(source_id)`.

Do not start with the whole planned six-tool surface. Start with the tools needed for one `Look deeper` path.

### P1: Store Escalation State

Right now, `IngestionJob` can carry an `answer_query` job, but smart mode needs its own trace.

Options:

- use `IngestionJob` with a `look_deeper` job type for the first slice;
- later add a dedicated `agent_runs` table if the trace becomes richer.

For the first slice, store:

- original `query_id`;
- Slack channel and thread timestamp;
- allowed evidence IDs;
- status;
- final rendered deeper answer;
- validation outcome.

### P1: Improve Health And Operator Visibility

Current health checks show database, Qdrant config, Slack config, and Toolhouse config. They do not show worker liveness, queued job count, failed job count, or last Slack sync time.

Before a polished demo, add an operator-facing status surface:

- worker enabled/disabled;
- queued answer jobs;
- failed jobs;
- last live Slack source sync;
- Toolhouse configured/available;
- last agent escalation status.

### P1: Live `Show sources` Click Verification

The Slack interactivity path is tested, and the worker posted live threaded answers, but the final human click path should still be verified against the live workspace before recording.

Checklist:

- ask a real question in `#cre-agent-qa`;
- wait for threaded reply;
- click `Show sources`;
- confirm ephemeral sources use live Slack-backed citations;
- confirm no stale demo-channel labels appear.

### P2: Move Beyond Demo Sync To Real Backfill

The live Slack metadata sync is excellent for demo readiness, but it is still seeded-demo oriented.

The production-shaped path still needs:

- bounded channel history backfill;
- thread-reply ingestion;
- file discovery and download;
- message and file event ingestion;
- incremental re-sync by cursor or timestamp.

This can wait until after one smart-agent path exists.

### P2: Real Semantic Retrieval

Qdrant is configured, but current hybrid retrieval still relies on keyword fallback.

Before broad agentic questions, add real semantic search for source chunks so `Look deeper` can ask richer questions without depending only on exact terms.

## Slack Interface Audit

### Current Vibe

The current Slack interface is useful and trustworthy, but plain:

- answers are text-first;
- sources are accessible by button;
- there is no progress state except the final reply;
- there is no smart escalation affordance yet;
- the personality is neutral and operational.

That is a good baseline. The next layer should make it feel quietly sharp, not chatty.

### Desired Vibe

The agent should feel nonchalant yet very intelligent:

- short first sentence that gives the answer;
- compact evidence signals;
- calm confidence without overexplaining;
- occasional understated judgment;
- no big assistant monologues;
- no fake certainty;
- no salesy flourish.

Example tone:

```text
Looks like the clean shortlist is 120 Main and 17 Pine.

- 120 Main St - 4,800 SF at $42/SF, available Q3 2026.
- 17 Pine St - 9,750 SF at $48/SF, available Jun 2026.

2 sources checked. Nothing over $50/SF made the cut.
```

For conflict answers:

```text
Use 62k SF for Harbor.

Priya's correction is newer and points back to the industrial inventory, so it outranks the older 58k row. The old value is still worth keeping as a superseded source, not as the current fact.
```

### Slack UI Upgrades

Add compact blocks, not heavy cards:

- top line: answer in one sentence;
- body: 2 to 4 bullets max;
- footer context: `2 sources checked`, `1 correction found`, `last source: today`;
- actions: `Show sources`, `Look deeper`, and sometimes one contextual follow-up.

Potential contextual follow-ups:

- `Compare rents`;
- `Explain conflict`;
- `Draft client note`;
- `Show only industrial`;
- `What changed?`.

Use follow-up buttons sparingly. The agent should feel smart because it chose the obvious next move, not because it sprayed options.

### Progress States

For smart mode, use calm status messages:

- `On it. Checking the messy bits.`
- `Found the likely answer. Verifying sources.`
- `One correction matters here.`
- `This is more judgment than lookup, so I am widening the pass.`

Avoid:

- overly cheerful filler;
- long disclaimers;
- pretending to think out loud;
- hidden chain-of-thought style text.

### Source Display Improvements

`Show sources` can become more useful without becoming noisy:

- group selected, supporting, and superseded evidence;
- include Slack permalinks when present;
- label file versus message evidence;
- show source freshness in plain language;
- show why a source won when there is conflict.

Example:

```text
Sources for: Why did you use 62k sq ft for Harbor Rd?

Selected
- source-corrections.csv - Priya, #cre-listings, today. Fresher correction.

Supporting
- Slack message - Priya, #cre-listings, today. Confirms source-of-truth guidance.

Superseded
- industrial-availability.csv - Priya, #cre-listings, today. Older 58k row.
```

## Next-Level Ideas To Preserve

### 1. Deal Memo Button

After an answer, offer `Draft client note` for recommendation-style queries.

Output:

- three-line client-ready summary;
- recommended property;
- caveat;
- citations.

This is high-demo-value because it turns retrieval into workflow output.

### 2. Correction Radar

When the agent detects a conflict, let it say:

```text
Small catch: Harbor has a newer correction. I used that instead of the older inventory row.
```

This makes the system feel intelligent without being theatrical.

### 3. Evidence Mood Ring

Add a tiny evidence confidence footer:

- `Clean match`;
- `Some judgment involved`;
- `Conflicting sources`;
- `Sparse evidence`.

This gives users calibration at a glance.

### 4. Daily CRE Brief

A scheduled or manual summary:

- new listings;
- changed facts;
- corrections;
- tenant-fit opportunities;
- stale or conflicting sources.

This would make the agent feel proactive while still grounded.

### 5. Deal-Room Memory

For each property, maintain a short rolling brief:

- current facts;
- latest correction;
- open questions;
- source trail;
- suggested next action.

This could later become the bridge to an actual graph/CRM story.

### 6. Private-Source Guardrail Preview

When channel scope is implemented, the agent can say:

```text
I found related internal notes, but I am not citing them in this channel.
```

Do not demo this as real ACL behavior until the permission model exists, but it is a strong future story.

### 7. Market-Readiness Lens

For tenant queries, return:

- best fit;
- why it fits;
- risk;
- what to verify before sending to client.

This is a better CRE demo than raw search results.

### 8. Source-Aware Reactions

Use reactions only as quiet state signals:

- add a check reaction when the final answer is posted;
- add a document reaction if sources were attached;
- add a warning-style reaction only for conflicts.

This should be subtle, not cute.

## Recommended Next Slice

Build the first `Look deeper` path in three small pieces:

1. add the Slack button and action handler;
2. package `query_id` plus allowed evidence into a strict escalation payload;
3. produce a local evidence-bound deeper synthesis with citation validation.

Only after that should the real Toolhouse API be plugged in.

This keeps the user-facing smart mode demoable even if Toolhouse credentials or API behavior need adjustment.

## Definition Of Ready For Real Toolhouse Agent Mode

Treat the system as ready for real Toolhouse integration when:

- `Look deeper` exists in Slack;
- the deeper path has a local evidence-bound implementation;
- output citation validation exists;
- live `Show sources` click has been verified;
- Toolhouse has a minimal backend tool surface;
- health/status exposes Toolhouse and worker state;
- the demo script clearly says Toolhouse is the synthesis layer, not the source of truth.
