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
- one full-corpus inventory moment;
- two fast deterministic wins over richer CRE fields;
- one threaded CSV comparison moment;
- one noisy hybrid retrieval win;
- one local tenant-fit synthesis win that escalates cleanly;
- one source-inspection moment;
- one follow-up modal or `Look deeper` moment;
- a crisp close that frames Toolhouse as the second pass, not the source of facts.

## Pre-Recording Checklist

Before you record, make sure:

- the app is running locally on the tunnel target port;
- the Cloudflare tunnel is live;
- `uv run cre-cli demo-doctor --live-toolhouse` returns `ready`;
- `uv run cre-cli demo-dry-run --live-toolhouse` returns `passed` and gives you replay commands for the answers you will show;
- `uv run cre-cli secret-scan` returns `passed` before anything is pushed or recorded;
- the local corpus has the full generated inventory loaded, not only the compact sample fixture; if tests recently reset the DB, run `uv run cre-cli import-samples` again;
- the answer thread can upload `Quick comparison CSV` files for instant and `Look deeper` answers;
- `#cre-listings` contains the seeded messages and Harbor correction thread;
- `#cre-listings` contains the last-mile watchlist, Beacon/Spruce tour notes, and access caveats;
- `#cre-market-research` contains the market and tenant-context messages;
- `#cre-agent-qa` is clean enough for the live questions;
- you know which questions you will paste or type;
- `Show sources` works if you are planning to click it;
- `Look deeper` works if you are planning to show Toolhouse live;
- you do not claim multiple real users or production-grade identity behavior.

## 4 To 5 Minute Script

### 0:00 to 0:25 - Open And Frame The Product

Say:

`This is a Slack-native CRE knowledge engine. It ingests the kinds of things a brokerage team actually works from - listing flyers, spreadsheets, field notes, corrections, tenant briefs, market notes, and quick Slack follow-ups - then answers questions with the source trail attached.`

`The important thing is that this is not just chat over documents. The backend normalizes property facts, tracks Slack messages and files, handles filters and proximity, keeps thread memory, and saves a replayable receipt for every answer.`

`This workspace is seeded with teammate personas in a single-user demo setup, so what I am demonstrating is retrieval, source handling, replay, and the Toolhouse handoff boundary, not a production identity system.`

### 0:25 to 0:55 - Show The Evidence Trail

Open `#cre-listings`.

Say:

`Here is the raw collaboration trail. Sarah posts polished listing details, John posts field notes, Priya posts corrections and source-of-truth guidance, and Maya posts a tenant requirement. The agent has to preserve those differences instead of flattening everything into one vague summary.`

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

`I ask the agent in a clean Q and A channel, but the evidence comes from the broader workspace context. The demo corpus also includes a larger deterministic inventory, so broad inventory questions no longer collapse back to only the hand-written examples.`

### 1:20 to 1:45 - Full-Corpus Inventory Win

Ask:

- `List all properties.`

Say:

`This is the broad inventory path. The answer summarizes the full deduped corpus, including the generated CRE backbone, while still keeping the hand-authored demo listings as inspectable evidence when they are selected.`

### 1:45 to 2:10 - Structured Retrieval And CSV Win

Ask:

- `What properties do we have available near 123 Main Street?`

Say while the answer is visible:

`This is a deterministic retrieval path. It uses stored coordinates, returns nearby properties with sources, and uploads the quick comparison as a CSV in the Slack thread instead of squeezing a table into message text.`

If the CSV share appears a few seconds after the answer, wait briefly and say:

`Slack file shares can land just after the answer update, but it is the same backend comparison table, exported in a format a broker can actually open.`

### 2:10 to 2:35 - Rich Structured Filter Win

Ask:

- `Show office buildings under $50/sq ft.`

Say:

`This is a second structured path. The filter is exact, and the query constructor now understands richer CRE fields like rent, sale terms, cap rates, clear height, dock doors, parking, coordinates, map links, status, and locality.`

### 2:35 to 3:00 - Aggregation Win

Ask:

- `What is the average rent for industrial listings under $35/SF?`

Say:

`This is not a text summary. It is aggregating deduped structured records across PDFs, spreadsheets, CSVs, and Slack-shaped notes, then saving the answer snapshot for replay.`

### 3:00 to 3:25 - Noisy Hybrid Retrieval Win

Ask:

- `Find whse opts with trk court and trlr parking.`

Say:

`This is the messy-user-query path. The system expands aliases, uses local lexical retrieval, PolyFuzz edit distance, character n-grams, and optional vector search if enabled, then still requires real source text matches before it treats a listing as evidence.`

### 3:25 to 4:05 - Tenant Fit And Toolhouse Win

Ask:

- `Which options look best for a logistics tenant under $35/SF available soon?`

Say:

`This is local synthesis before Toolhouse. It scores price, size, timing, source quality, and logistics language, then invites Look deeper only after the backend has selected the evidence bundle.`

Click `Look deeper`.

Say while the Toolhouse answer appears:

`Now Toolhouse is doing the second pass through the backend MCP boundary. It can rank, compare, inspect timelines, and look for conflicts, but it still has to cite backend-minted evidence IDs. It cannot invent a listing or run arbitrary SQL.`

If a second CSV appears, say:

`The deeper-review comparison also comes back as a Slack CSV, so Toolhouse-generated tables use the same clean delivery path as instant answers.`

### 4:05 to 4:25 - Conflict Resolution Win

Ask:

- `Why did you use 62k sq ft for Harbor Rd?`

Say:

`This demonstrates conflict handling. The agent is not silently merging facts. It is preferring fresher, stronger evidence and showing why.`

### 4:25 to 4:45 - Source Loop

Trigger `Show sources`.

Say:

`This is the source loop. The important part is not that the answer sounds confident. The important part is that the source bundle points back to actual rows, pages, and Slack messages, and the same bundle can be replayed or handed to Toolhouse without letting the agent invent new evidence.`

### 4:45 to 5:00 - Close With Next Layer

Say:

`The current core is the evidence path: ingest, normalize, retrieve, answer, cite, export, and replay. Toolhouse is the deeper synthesis layer over that bundle, which is exactly where I want agentic reasoning to live.`

## Shorter 3-Minute Fallback

If time is tight, do only this:

1. show `#cre-listings` with the Harbor correction;
2. ask `List all properties.`;
3. ask `What properties do we have available near 123 Main Street?` and point out the CSV attachment;
4. ask `Find whse opts with trk court and trlr parking.`;
5. ask `Which options look best for a logistics tenant under $35/SF available soon?`, then click `Look deeper` if live Toolhouse is healthy;
6. trigger `Show sources`.

## Follow-Up Modal Cutaway

If you have another 20 seconds, click `Follow Up with Agent ⚡` on a prior answer.

Say:

`The follow-up modal is thread-aware. It carries forward prior query history and evidence IDs, shows cached suggestions when Toolhouse has already produced them, and offers Generate suggestions when the cache is empty. A suggested follow-up runs through a backend-owned instant template; a custom question can stay instant, auto-route, or go to Agent mode.`

## Optional Stress Reel

Use these if the recording has extra room or you want quick cuts between Slack answers:

- `What do we know about 18 Beacon Freight?`
- `Show industrial listings available soon under $35/SF.`
- `Compare industrial listings under $35/SF available soon.`
- `Show cap rates above 5%.`
- `Which listings have map links or coordinates?`
- `What is the average rent for industrial listings under $35/SF?`
- `Forecast cap rates for 2029 from market vibes.`

The last one should show the unsupported-query guardrail instead of bluffing.

## Lines To Avoid

Do not say:

- `This already has production-grade permissions.`
- `These are real distinct Slack users.`
- `Toolhouse is powering every answer.`
- `This supports broad enterprise Slack ingestion today.`
- `The generated corpus is scraped live market truth.`

## Strong Closing Sentence

Use this verbatim if you want a clean finish:

`The system already proves the hard part: grounded answers over messy workspace evidence, with structured data, Slack-native receipts, clean CSV comparisons, and a bounded Toolhouse handoff. The agent can reason, but the backend keeps the facts honest.`
