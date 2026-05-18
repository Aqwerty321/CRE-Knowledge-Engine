# Pre-Toolhouse Gap Checklist

## Purpose

This checklist captures the remaining gaps before bringing Toolhouse agent mode into the demo path.

The goal is not to block Toolhouse forever. The goal is to make sure Toolhouse lands on top of a stable, source-grounded Slack and retrieval spine.

## Current State Summary

What is already true in the current repo state:

- the local structured, generic heuristic, tenant-fit, and hybrid answer paths are tested;
- the Slack mention loop exists with queueing, a lifespan-managed background worker, threaded replies, `Show sources`, and local `Look deeper`;
- the live callback URL is working through the Cloudflare tunnel;
- the demo Slack workspace is seeded with persona messages and a correction thread;
- Slack demo files are uploaded and synced into the evidence model with live Slack file IDs, timestamps, channel names, and permalinks;
- the app can answer from the Slack-backed evidence store;
- the local Toolhouse boundary can package evidence, run a bounded deeper review, and validate cited evidence IDs;
- deterministic Toolhouse-facing functions exist in [app/toolhouse/tools.py](../app/toolhouse/tools.py).

What is not yet true:

- there is no real Toolhouse API call yet because credentials/runtime details have not been provided;
- live Slack ingestion is still demo-sync oriented rather than full continuous backfill/event ingestion.

## Gaps To Close Before Toolhouse Agent Mode

### 1. Build The Toolhouse Boundary

Current evidence:

- [app/toolhouse/local_agent.py](../app/toolhouse/local_agent.py) packages evidence and validates cited evidence IDs.
- [app/toolhouse/tools.py](../app/toolhouse/tools.py) exposes deterministic backend tool functions.
- The final contract in [final-implementation-spec.md](final-implementation-spec.md) expects Toolhouse to receive grounded context and use backend retrieval tools.

Status:

- local request packaging and validation are implemented;
- the real Toolhouse client call remains to be wired.

What to add:

- a minimal Toolhouse integration module;
- one evidence-bound `Look deeper` execution path;
- a strict input package containing query text, route mode, evidence IDs, and source summaries.

### 2. Add The `Look deeper` Slack Action

Current evidence:

- [app/slack/runtime.py](../app/slack/runtime.py) registers `show_sources` and `look_deeper`.
- [app/slack/service.py](../app/slack/service.py) builds both buttons and queues `look_deeper` jobs.
- [app/workers/query_worker.py](../app/workers/query_worker.py) processes `look_deeper` jobs.

Status:

- complete locally; replace the local deeper review call with Toolhouse when credentials are available.

What to add:

- a `Look deeper` button in the answer blocks when the route and evidence bundle support it;
- a Slack action handler for that button;
- status messaging so the user sees the deeper review is in progress and then completed.

### 3. Expose Backend Tools For Toolhouse

Current evidence:

- the final architecture expects tools like `search_properties`, `aggregate_properties`, `search_source_chunks`, `get_source_detail`, `nearby_properties`, and `explain_evidence`.
- none of these are yet exposed as a Toolhouse-facing tool surface.

Status:

- deterministic internal tools exist for the first Toolhouse wrapper.

What to add:

- a minimal backend tool layer with boring, deterministic interfaces;
- schema-stable outputs that carry evidence IDs and source metadata;
- one narrow first slice, not the full six-tool surface all at once.

### 4. Validate Toolhouse Output Against Evidence IDs

Current evidence:

- the production docs require Toolhouse citations to be checked against allowed evidence IDs.

Status:

- local validation exists and should be kept in front of real Toolhouse output.

What to add:

- an evidence whitelist validator;
- rejection or downgrade behavior if Toolhouse references unknown or unsupported sources;
- formatting through the same citation layer used by deterministic answers.

### 5. Finish The Live Slack Ingestion Story

Current evidence:

- the current live Slack slice handles `app_mention` and `Show sources`.
- the final spec still expects message backfill, thread reply ingestion, file listing, file download, and new message/file ingestion.

Gap:

- Toolhouse would look too early if the upstream Slack ingestion story is still partial.

What to add before or alongside Toolhouse:

- bounded backfill for one configured channel;
- thread-reply fetch path;
- file ingestion path;
- at least one live non-mention Slack source entering the evidence model.

### 6. Keep Slack File Upload Scope Working

Current evidence:

- Slack message seeding works;
- Slack file upload seeding works;
- live Slack demo source sync resolves uploaded file metadata into the evidence model.

Gap:

- this path is still a demo sync path, not continuous live file ingestion.

Why this matters for Toolhouse:

- the deeper synthesis story is much stronger when the workspace visibly contains research files and listing files, not only persona messages.

### 7. Verify One Real Human Mention End To End

Current evidence:

- the callback URL and local runtime are working;
- local Slack loop tests pass;
- workspace seeding is complete for messages.

Gap:

- there is still value in one final real human mention to the bot before introducing Toolhouse complexity.

What to prove:

- mention event enters the app;
- queue path runs;
- thread reply appears in Slack;
- `Show sources` works in the live workspace.

### 8. Decide Whether Keyword Fallback Is Enough For The First Toolhouse Demo

Current evidence:

- hybrid retrieval currently includes a keyword fallback path;
- Toolhouse is supposed to deepen synthesis, not compensate for missing evidence retrieval.

Gap:

- if the first Toolhouse demo depends on semantic breadth, decide whether the current fallback quality is enough or whether Qdrant-backed retrieval should be strengthened first.

## Recommended Order Before Toolhouse

Completed locally:

- `Look deeper` action;
- evidence package;
- evidence ID validator;
- deterministic backend tool functions;
- data-quality audit;
- broader heuristic answer layer.

Use this order for the real Toolhouse API wiring:

1. verify one live human `Show sources` click in Slack;
2. verify one live human `Look deeper` click in Slack;
3. provide Toolhouse credentials/runtime details;
4. replace the local deeper-review call with Toolhouse;
5. keep validation in front of posting;
6. record one clean demo pass.

## What Is Safe To Defer

You do not need these before the first Toolhouse demo:

- full six-tool surface at production depth;
- multi-user Slack identity semantics;
- broad workspace backfill;
- broad multi-channel administration;
- polished market-analysis orchestration across many channels.

## Minimum Toolhouse-Ready Bar

Treat the system as ready for Toolhouse agent mode when all of these are true:

- the live Slack mention loop works end to end;
- `Show sources` works end to end;
- the demo workspace has believable evidence in messages and ideally files;
- one `Look deeper` action is wired;
- Toolhouse receives only grounded context;
- Toolhouse output is validated against evidence IDs before posting.

Until then, Toolhouse should be framed as the next layer rather than the current core differentiator.
