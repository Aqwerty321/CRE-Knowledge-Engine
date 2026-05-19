# Slack Demo Video Script

## Purpose

This is the tight 3 to 5 minute version of the Slack demo.

Use it when recording the final submission video so the narrative stays focused, honest, and easy to follow.

For the fuller workspace setup and channel seeding plan, see [slack-demo-runbook.md](slack-demo-runbook.md).

## Target Length

- ideal: 4 minutes;
- acceptable: 3 to 5 minutes.

## What This Script Optimizes For

- clear product definition;
- visible evidence trail in Slack;
- two fast deterministic wins;
- one expanded aggregation win;
- one noisy hybrid retrieval win;
- one local tenant-fit synthesis win;
- one source-inspection moment;
- a crisp close that frames Toolhouse as the second pass, not the source of facts.

## Pre-Recording Checklist

Before you record, make sure:

- the app is running locally on the tunnel target port;
- the Cloudflare tunnel is live;
- `uv run cre-cli demo-doctor --live-toolhouse` returns `ready`;
- `uv run cre-cli demo-dry-run --live-toolhouse` returns `passed` and gives you replay commands for the answers you will show;
- `uv run cre-cli secret-scan` returns `passed` before anything is pushed or recorded;
- `#cre-listings` contains the seeded messages and Harbor correction thread;
- `#cre-listings` contains the last-mile watchlist, Beacon/Spruce tour notes, and access caveats;
- `#cre-market-research` contains the market and tenant-context messages;
- `#cre-agent-qa` is clean enough for the live questions;
- you know which questions you will paste or type;
- `Show sources` works if you are planning to click it;
- you do not claim multiple real users or production-grade identity behavior.

## 4 To 5 Minute Script

### 0:00 to 0:25 - Open And Frame The Product

Say:

`This is a Slack-native CRE knowledge engine. It ingests the kinds of things a brokerage team actually shares in Slack, like listing flyers, spreadsheets, field notes, corrections, tenant briefs, and quick follow-up messages, then answers questions with sources attached.`

`This workspace is seeded with teammate personas in a single-user demo setup, so what I am demonstrating is retrieval, source handling, replay, and the Toolhouse handoff boundary, not a production identity system.`

### 0:25 to 0:55 - Show The Evidence Trail

Open `#cre-listings`.

Say:

`Here is the raw collaboration trail. Sarah posts polished listing details, John posts field notes, Priya posts corrections and source-of-truth guidance, and Maya posts a tenant requirement.`

Show:

- Sarah's 120 Main message;
- John's Union Yard note;
- Priya's Harbor correction;
- Sarah's 18 Beacon Freight watchlist note;
- John's 42 Spruce Flex tour note;
- the Harbor reply thread.

### 0:55 to 1:20 - Move To The Agent Channel

Open `#cre-agent-qa`.

Say:

`I ask the agent in a clean Q and A channel, but the evidence comes from the seeded workspace context.`

### 1:20 to 1:50 - Structured Retrieval Win

Ask:

- `What properties do we have available near 123 Main Street?`

Say while the answer is visible:

`This is a deterministic retrieval path. It is using seeded coordinates and returning nearby properties with sources, not hallucinating a narrative answer.`

### 1:50 to 2:15 - Numeric Filter Win

Ask:

- `Show office buildings under $50/sq ft.`

Say:

`This is a second structured path. The filter is exact, and the answer now has enough corpus depth to include a newer follow-up office option while still excluding the higher-priced one.`

### 2:15 to 2:40 - Aggregation Win

Ask:

- `What is the average rent for industrial listings under $35/SF?`

Say:

`This is not a text summary. It is aggregating deduped structured records across PDFs, spreadsheets, CSVs, and Slack-shaped notes, then saving the answer snapshot for replay.`

### 2:40 to 3:10 - Noisy Hybrid Retrieval Win

Ask:

- `Find whse opts with trk court and trlr parking.`

Say:

`This is the messy-user-query path. The system expands aliases, uses local lexical retrieval, PolyFuzz edit distance, character n-grams, and optional vector search if enabled, then still requires real source text matches before it treats a listing as evidence.`

### 3:10 to 3:40 - Tenant Fit Win

Ask:

- `Which options look best for a logistics tenant under $35/SF available soon?`

Say:

`This is local synthesis before Toolhouse. It scores price, size, timing, source quality, and logistics language, then invites Look deeper only after the backend has selected the evidence bundle.`

### 3:40 to 4:05 - Conflict Resolution Win

Ask:

- `Why did you use 62k sq ft for Harbor Rd?`

Say:

`This demonstrates conflict handling. The agent is not silently merging facts. It is preferring fresher, stronger evidence and showing why.`

### 4:05 to 4:30 - Source Loop

Trigger `Show sources`.

Say:

`This is the source loop. The important part is not that the answer sounds confident. The important part is that the source bundle can be inspected, replayed, and handed to Toolhouse without letting the agent invent new evidence.`

### 4:30 to 4:55 - Close With Next Layer

Say:

`The current core is the evidence path: ingest, normalize, retrieve, answer, cite, and replay. Toolhouse is the second pass over that bundle, which is exactly where I want agentic synthesis to live.`

## Shorter 3-Minute Fallback

If time is tight, do only this:

1. show `#cre-listings` with the Harbor correction;
2. ask `What properties do we have available near 123 Main Street?`;
3. ask `Find whse opts with trk court and trlr parking.`;
4. ask `Which options look best for a logistics tenant under $35/SF available soon?`;
5. ask `Why did you use 62k sq ft for Harbor Rd?`;
6. trigger `Show sources`.

## Optional Stress Reel

Use these if the recording has extra room or you want quick cuts between Slack answers:

- `What do we know about 18 Beacon Freight?`
- `Show industrial listings available soon under $35/SF.`
- `What is the average rent for industrial listings under $35/SF?`
- `Forecast cap rates for 2029 from market vibes.`

The last one should show the unsupported-query guardrail instead of bluffing.

## Lines To Avoid

Do not say:

- `This already has production-grade permissions.`
- `These are real distinct Slack users.`
- `Toolhouse is already powering the main answer flow.`
- `This supports broad enterprise Slack ingestion today.`

## Strong Closing Sentence

Use this verbatim if you want a clean finish:

`The system already proves the hard part: grounded answers over messy workspace evidence. Toolhouse is the deeper synthesis layer, but the source discipline is already in place.`
