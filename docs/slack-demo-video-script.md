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
- one hybrid/conflict win;
- one trust-receipt moment;
- a crisp close that frames Toolhouse as the next layer, not the current core.

## Pre-Recording Checklist

Before you record, make sure:

- the app is running locally on the tunnel target port;
- the Cloudflare tunnel is live;
- `uv run cre-cli demo-doctor --live-toolhouse` returns `ready`;
- `uv run cre-cli demo-dry-run --live-toolhouse` returns `passed` and gives you replay commands for the answers you will show;
- `uv run cre-cli secret-scan` returns `passed` before anything is pushed or recorded;
- `#cre-listings` contains the seeded messages and Harbor correction thread;
- `#cre-market-research` contains the market and tenant-context messages;
- `#cre-agent-qa` is clean enough for the live questions;
- you know which questions you will paste or type;
- `Show sources` works if you are planning to click it;
- you do not claim multiple real users or production-grade identity behavior.

## 4-Minute Script

### 0:00 to 0:25 - Open And Frame The Product

Say:

`This is a Slack-native CRE knowledge engine. It ingests the kinds of things a brokerage team actually shares in Slack, like listing flyers, spreadsheets, field notes, corrections, and tenant requests, then answers questions with grounded sources.`

`This workspace is seeded with teammate personas in a single-user demo setup, so what I am demonstrating is source-aware retrieval and answering, not a full production identity model.`

### 0:25 to 0:55 - Show The Evidence Trail

Open `#cre-listings`.

Say:

`Here is the raw collaboration trail. Sarah posts polished listing details, John posts field notes, Priya posts corrections and source-of-truth guidance, and Maya posts a tenant requirement.`

Show:

- Sarah's 120 Main message;
- John's Union Yard note;
- Priya's Harbor correction;
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

`This is a second structured path. The value here is that the filter is exact, and the answer is still grounded in the original source material.`

### 2:15 to 2:50 - Hybrid Retrieval Win

Ask:

- `Find listings that mention loading access or yard space.`

Say:

`This is where the system has to go beyond clean structured fields. It combines listing material and unstructured notes like field observations to find evidence tied to operational language.`

### 2:50 to 3:20 - Conflict Resolution Win

Ask:

- `Why did you use 62k sq ft for Harbor Rd?`

Say:

`This demonstrates conflict handling. The agent is not silently merging facts. It is preferring fresher, stronger evidence and showing why.`

### 3:20 to 3:45 - Trust Loop

Trigger `Show sources`.

Say:

`This is the trust loop. The important thing is not just that the answer sounds plausible. The important thing is that the answer can be inspected and replayed.`

### 3:45 to 4:10 - Close With Next Layer

Say:

`The current core is the evidence spine: ingest, normalize, retrieve, answer, and cite. The next layer is Toolhouse-backed deeper synthesis on top of this grounded evidence model, not instead of it.`

## Shorter 3-Minute Fallback

If time is tight, do only this:

1. show `#cre-listings` with the Harbor correction;
2. ask `What properties do we have available near 123 Main Street?`;
3. ask `Find listings that mention loading access or yard space.`;
4. ask `Why did you use 62k sq ft for Harbor Rd?`;
5. trigger `Show sources`.

## Lines To Avoid

Do not say:

- `This already has production-grade permissions.`
- `These are real distinct Slack users.`
- `Toolhouse is already powering the main answer flow.`
- `This supports broad enterprise Slack ingestion today.`

## Strong Closing Sentence

Use this verbatim if you want a clean finish:

`The system already proves the hard part: grounded answers over messy workspace evidence. The Toolhouse layer is the next step for deeper synthesis, but the trust model is already in place.`
