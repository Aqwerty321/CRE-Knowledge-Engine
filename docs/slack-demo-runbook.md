# Slack Demo Runbook

## Purpose

This runbook turns the persona sheet into a practical final-demo walkthrough.

Use it when preparing the Slack workspace, seeding content, and recording the live demo.

This runbook assumes:

- one real agent bot;
- one real human demo operator;
- fictional teammate personas represented through seeded messages and uploaded files;
- no claim of true per-user personalization or permission differences between real Slack users.

See [slack-demo-persona-sheet.md](slack-demo-persona-sheet.md) for persona definitions and honesty guardrails.
For the shorter recording version, see [slack-demo-video-script.md](slack-demo-video-script.md).
For remaining implementation gaps before Toolhouse, see [pre-toolhouse-gap-checklist.md](pre-toolhouse-gap-checklist.md).

## Demo Goal

Make the workspace feel like a believable CRE team collaboration space where the agent has to answer from:

- listing flyers;
- inventory sheets;
- field notes;
- corrections over time;
- market research;
- tenant needs.

The strongest story is not `look at my bot`. The strongest story is `look at how the bot grounds answers in the messy information a CRE team actually shares`.

## Channel Layout

Use these channels:

- `#cre-listings`: primary evidence channel for listings, corrections, notes, and listing-related questions;
- `#cre-market-research`: supporting market context and tenant requirement inputs;
- `#cre-private-demo`: internal-only notes to demonstrate channel-scoped retrieval boundaries;
- `#cre-agent-qa`: live query channel for the final walkthrough.

## Pre-Demo Workspace State

Before recording, make sure the workspace shows:

- historical seeded messages in `#cre-listings`;
- at least one correction thread in `#cre-listings`;
- market and tenant-supporting context in `#cre-market-research`;
- at least one internal-only note in `#cre-private-demo`;
- a clean `#cre-agent-qa` channel where the live questions will happen;
- the agent bot present in all channels it needs to read or answer in;
- uploaded files if the app has the required Slack upload scope;
- message-only fallback if file upload scope is still missing.

## File Plan

If Slack file upload permissions are available, use this mapping.

CLI commands:

- preview: `uv run cre-cli seed-slack-files --dry-run`
- apply: `uv run cre-cli seed-slack-files`
- import live Slack metadata into the evidence model: `uv run cre-cli sync-slack-demo-sources`
- backfill a real configured channel: `uv run cre-cli sync-slack-channel-history --channel-id C123 --channel-name cre-listings --recent-limit 100`

Regenerate the large CSV shard set before seeding if needed:

```bash
uv run cre-cli build-large-corpus --rows 2400 --seed 20260519
```

### Seed `#cre-listings`

- `main-street-office-flyer.pdf`
- `elm-ave-industrial-flyer.pdf`
- `downtown-office-inventory.csv`
- `industrial-availability.csv`
- `slack-field-notes.txt`
- `source-corrections.csv`
- `global-cre-corpus-us-1.csv`
- `global-cre-corpus-us-2.csv`

### Seed `#cre-market-research`

- `q2-metro-market-snapshot.pdf`
- `market-street-retail-brief.pdf`
- `tenant-requirements-summary.txt`
- `broker-availability-tracker.xlsx`
- `global-cre-corpus-europe-1.csv`
- `global-cre-corpus-europe-2.csv`

### Seed `#cre-private-demo`

- `source-corrections.csv`
- `broker-availability-tracker.xlsx`

If file uploads are still unavailable in Slack, keep the local importer as the source of truth for file-backed evidence and use the Slack messages to create the visible team context.

## Channel-By-Channel Seed Script

Post in this order so the workspace feels chronological and intentional.

### `#cre-listings`

Use these four seeded messages:

1. `Sarah: Uploaded the Main Street office flyer. 120 Main is still targeting Q3 2026, asking $42/SF.`
2. `John: The Union Yard space at 64 Union Yard is available immediately. Around 31k SF, industrial, asking $24/SF.`
3. `Priya: Harbor Rd got updated yesterday. 240 Harbor is now 62k SF, not 58k. Use the industrial inventory as source of truth.`
4. `Maya: Tenant wants industrial near Main with loading access, ideally under $35/SF and available soon.`

Add this thread reply under Priya's Harbor correction:

- `Sarah: Thanks. I'm updating the tracker and keeping 62k SF as the current Harbor Rd figure.`

What this channel proves:

- direct structured facts;
- unstructured field notes;
- conflict and freshness resolution;
- hybrid retrieval over operational language such as `loading access` and `yard space`.

### `#cre-market-research`

Use these two seeded messages:

1. `Maya: Uploaded the Q2 metro market snapshot and retail brief for market context and demand signals.`
2. `Priya: Tenant requirements summary is attached here for recommendation and look-deeper testing.`

What this channel proves:

- synthesis inputs exist outside the listings channel;
- market context and tenant requirements can support deeper recommendation answers;
- `Look deeper` has a believable evidence base.

### `#cre-private-demo`

Use these two seeded messages:

1. `Private demo note: Harbor underwriting assumptions and corrected square footage are here for internal review only.`
2. `Internal note: Keep private-demo scoped to visibility and source-controls checks during the live walkthrough.`

What this channel proves:

- the system can be framed as respecting channel scope;
- some information is internal-only and not just public chatter;
- you can explain channel-bounded retrieval without pretending to have real multi-user authorization logic.

### Seed `#cre-agent-qa`

Use this seeded setup message:

- `QA seed: try queries like "What properties do we have available near 123 Main Street?", "Find whse opts with trk court and trlr parking.", "Which options look best for a logistics tenant under $35/SF available soon?", and "Why did you use 62k sq ft for Harbor Rd?" once ingestion is wired live.`

Then keep the channel mostly clean for the live demo questions.

What this channel proves:

- the bot is usable in a focused Q and A workflow;
- the demonstration stays readable and easy to follow;
- the audience can separate evidence channels from answer channels.

## Recommended Live Demo Sequence

Before recording, run the local preflight commands:

```bash
make recover-demo
uv run cre-cli eval-golden
uv run cre-cli demo-doctor
uv run cre-cli demo-dry-run --live-toolhouse
uv run cre-cli secret-scan
uv run cre-cli submission-report --format markdown --output .runtime/submission-report.md
```

For any answer you want to inspect or show outside Slack, copy the returned `query_id` and run:

```bash
uv run cre-cli replay-query <query-id>
```

That replay payload is the demo source receipt: route decision, reason codes, filters, evidence IDs, source summaries, dependency state, rendered answer, and saved Toolhouse/local agent traces when present. The submission report is a concise artifact you can keep open while recording or use as the final pre-push checklist.

### Phase 1: Set Context

Open `#cre-listings` first.

Say:

`This workspace is seeded with realistic teammate personas. The point is not fake roleplay. The point is to give the agent the same kinds of evidence a real CRE team produces: flyers, spreadsheets, field notes, corrections, and tenant requests.`

Show:

- Sarah's listing message;
- John's field note;
- Priya's Harbor correction;
- Sarah's 18 Beacon Freight watchlist note;
- John's 42 Spruce Flex tour note;
- the Harbor thread reply.

### Phase 2: Show The Agent Channel

Switch to `#cre-agent-qa`.

Say:

`I ask the agent in a clean channel, but the evidence comes from the broader workspace context it has ingested.`

### Phase 3: Run The Structured Query

Ask:

- `What properties do we have available near 123 Main Street?`

What to emphasize:

- deterministic proximity search;
- short answer format;
- cited evidence.

### Phase 4: Run The Numeric Filter Query

Ask:

- `Show office buildings under $50/sq ft.`

What to emphasize:

- exact filtering;
- exclusion of the wrong office candidate;
- source-grounded output.

### Phase 5: Run The Aggregation Query

Ask:

- `What is the average rent for industrial listings under $35/SF?`

What to emphasize:

- deduped aggregation over the larger industrial set;
- evidence comes from multiple source types;
- the answer can be replayed from the saved snapshot.

### Phase 6: Run The Noisy Hybrid Query

Ask:

- `Find whse opts with trk court and trlr parking.`

What to emphasize:

- the answer combines formal listing material and informal notes;
- shorthand like `whse`, `trk`, and `trlr` is normalized through local retrieval;
- this is where hybrid retrieval matters.

### Phase 7: Run The Tenant-Fit Query

Ask:

- `Which options look best for a logistics tenant under $35/SF available soon?`

What to emphasize:

- local synthesis happens before Toolhouse;
- the candidate set is still source-bounded;
- `Look deeper` is an escalation over the selected evidence bundle.

### Phase 8: Run The Conflict Query

Ask:

- `Why did you use 62k sq ft for Harbor Rd?`

What to emphasize:

- freshness and authority handling;
- correction over older conflicting data;
- explicit reasoning with sources instead of silent merging.

### Phase 7: Show Sources

Click or trigger `Show sources`.

What to emphasize:

- the answer is replayable;
- the evidence can be inspected directly;
- the user can understand exactly where the claim came from.

### Phase 8: Run The Recommendation Query

Ask:

- `What are the best three options for a tenant needing industrial near Main under $35/SF?`

If `Look deeper` is ready, trigger it.

What to emphasize:

- recommendation is layered on top of grounded retrieval;
- deeper synthesis does not replace citations;
- Toolhouse is an escalation path, not the source of truth.

## Tight Live Talk Track

Use this if you want a concise, repeatable script.

### Opening

`This is a Slack-native CRE knowledge engine. I seeded the workspace with realistic teammate personas so the system has to reason over the kinds of evidence a real brokerage team shares: listing flyers, field notes, spreadsheets, corrections, and tenant requests.`

`I only have one real Slack user in this workspace, so I am not claiming a production identity model here. What I am demonstrating is grounded retrieval, provenance, and Slack-native answering.`

### When Showing `#cre-listings`

`Here you can see the evidence trail: Sarah posts polished listing data, John posts messy field notes, Priya posts corrections and source-of-truth guidance, and Maya posts tenant needs.`

### When Moving To `#cre-agent-qa`

`The agent answers in a clean channel, but it uses the evidence ingested from the workspace context.`

### After The First Good Answer

`The key thing is that this is not just a chatbot response. The answer is attached to evidence that can be surfaced and replayed.`

### When Showing `Show sources`

`This is the source loop. Every factual answer should be inspectable, not just plausible.`

### When Showing A Conflict Answer

`Here the agent is resolving conflicting information over time. It is not silently merging facts; it is choosing the fresher, stronger evidence and showing why.`

### When Showing `Look deeper`

`The deeper path is where synthesis happens, but it still starts from grounded evidence. The agent layer is not allowed to invent primary facts.`

### Closing

`For this take-home, the important thing is that the system can ingest workspace knowledge, preserve source receipts, answer in Slack, and explain where the answer came from.`

## Honesty Guardrails For The Demo

Do say:

- `These personas are seeded teammate voices in a single-user workspace.`
- `This demonstrates grounded retrieval and source-aware answering.`
- `Channel context is part of the evidence model.`

Do not say:

- `This is fully personalized per user.`
- `This proves production authorization semantics between multiple real Slack users.`
- `This workspace contains real independent authorship from separate Slack identities.`

## If Time Gets Tight

Use this compressed version:

1. Show `#cre-listings` with the Harbor correction.
2. Ask `What properties do we have available near 123 Main Street?`
3. Ask `Find whse opts with trk court and trlr parking.`
4. Ask `Which options look best for a logistics tenant under $35/SF available soon?`
5. Ask `Why did you use 62k sq ft for Harbor Rd?`
6. Trigger `Show sources`.

That is enough to prove:

- structured retrieval;
- hybrid retrieval;
- conflict resolution;
- trust and evidence replay.
