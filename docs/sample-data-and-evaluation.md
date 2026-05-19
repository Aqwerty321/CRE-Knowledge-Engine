# Sample Data And Evaluation Plan

## Dataset Goals

The sample dataset should be realistic, deliberately overlapping, and large enough to make the demo feel like a working workspace rather than a canned lookup table. It should prove that the bot can handle Slack messages, PDFs, CSVs, Excel files, duplicates, numeric filters, dates, proximity, citations, noisy operational language, local synthesis, and replay.

Current size: 15 files plus 8 Slack-shaped messages, for 23 importable sources and 25 seeded property rows.

The sample dataset is also the reproducible evaluation harness. It should be importable locally without a live Slack workspace while preserving Slack-shaped metadata.

For the human voices used to seed the Slack workspace, see [slack-demo-persona-sheet.md](slack-demo-persona-sheet.md).

## Demo Channel

Use one public Slack channel for the cleanest demo:

```text
#cre-listings-demo
```

Seed it with:

- property flyers;
- inventory spreadsheets;
- a market note;
- Slack messages from teammates;
- a few duplicate or overlapping facts.

## Proposed Files

| ID | File | Type | Purpose |
| --- | --- | --- | --- |
| F1 | `main-street-office-flyer.pdf` | PDF | Direct property flyer for 120 Main St. |
| F2 | `elm-ave-industrial-flyer.pdf` | PDF | Industrial listing near 123 Main St. |
| F3 | `market-street-retail-brief.pdf` | PDF | Retail/mixed-use example and semantic retrieval. |
| F4 | `q2-metro-market-snapshot.pdf` | PDF | Narrative report for Toolhouse synthesis. |
| F5 | `downtown-office-inventory.csv` | CSV | Office filters under and over $50/sq ft. |
| F6 | `industrial-availability.csv` | CSV | Industrial aggregation and price filters. |
| F7 | `broker-availability-tracker.xlsx` | XLSX | Excel parsing and duplicate facts. |
| F8 | `slack-field-notes.txt` | Text | Text attachment with messy notes. |
| F9 | `tenant-requirements-summary.txt` | Text | Synthesis input for recommendations. |
| F10 | `source-corrections.csv` | CSV | Conflicting freshness example. |
| F11 | `last-mile-industrial-watchlist.csv` | CSV | Richer last-mile industrial options with truck court and trailer-parking language. |
| F12 | `client-tour-notes.txt` | Text | Messy tour feedback that overlaps with structured watchlist rows. |
| F13 | `tenant-expansion-brief.txt` | Text | Tenant-fit context without structured property rows. |
| F14 | `retail-office-followups.csv` | CSV | More office and retail options for filter and exclusion tests. |
| F15 | `access-constraints-notes.txt` | Text | Operational caveats without direct structured rows. |

## Seeded Properties

Use a fictional market but include coordinates so proximity search is deterministic.

Anchor address for demo proximity:

| Address | Lat | Lng |
| --- | --- | --- |
| 123 Main Street | 40.75050 | -73.99700 |

Property records:

| Address | Type | Sq Ft | Price/SF | Availability | Lat | Lng | Primary Source |
| --- | --- | ---: | ---: | --- | ---: | ---: | --- |
| 120 Main St | office | 4,800 | 42.00 | Q3 2026 | 40.75070 | -73.99670 | `main-street-office-flyer.pdf` p. 1 |
| 130 Elm Ave | industrial | 18,500 | 32.00 | Immediate | 40.75220 | -73.99930 | `elm-ave-industrial-flyer.pdf` p. 1 |
| 17 Pine St | office | 9,750 | 48.00 | Jun 2026 | 40.74490 | -73.99270 | `downtown-office-inventory.csv` row 2 |
| 88 Foundry Ln | industrial | 44,000 | 21.50 | Q2 2026 | 40.74300 | -74.00400 | `industrial-availability.csv` row 2 |
| 240 Harbor Rd | industrial | 62,000 | 18.00 | Aug 2026 | 40.73950 | -74.01020 | `industrial-availability.csv` row 3 |
| 455 Market St | retail | 7,200 | 55.00 | Now | 40.75460 | -73.99150 | `market-street-retail-brief.pdf` p. 2 |
| 700 Logistics Pkwy | industrial | 120,000 | 12.75 | Q4 2026 | 40.72500 | -74.02500 | `broker-availability-tracker.xlsx` sheet `Industrial` row 4 |
| 310 Canal Works | mixed_use | 15,600 | 39.00 | May 2026 | 40.74620 | -74.00190 | `broker-availability-tracker.xlsx` sheet `MixedUse` row 2 |
| 64 Union Yard | industrial | 31,000 | 24.00 | Immediate | 40.75180 | -74.00640 | Slack message by John |
| 900 North Loop | office | 22,000 | 61.00 | Jan 2027 | 40.76100 | -73.98800 | `downtown-office-inventory.csv` row 5 |
| 18 Beacon Freight | industrial | 36,000 | 26.00 | Immediate | 40.75090 | -74.00210 | `last-mile-industrial-watchlist.csv` row 2 |
| 42 Spruce Flex | industrial | 26,000 | 29.50 | Jul 2026 | 40.74710 | -74.00060 | `last-mile-industrial-watchlist.csv` row 3 |
| 510 River Cold Storage | industrial | 54,000 | 34.50 | Sep 2026 | 40.74120 | -74.00880 | `last-mile-industrial-watchlist.csv` row 4 |
| 75 Orchard Office | office | 6,800 | 44.00 | Jul 2026 | 40.74600 | -73.99050 | `retail-office-followups.csv` row 2 |
| 22 Gallery Row | retail | 5,200 | 49.00 | Jun 2026 | 40.75400 | -73.99090 | `retail-office-followups.csv` row 3 |
| 600 Skyline Office | office | 18,000 | 52.00 | Nov 2026 | 40.75990 | -73.98420 | `retail-office-followups.csv` row 4 |

## Slack Message Seeds

Create messages like these in the demo channel:

```text
Sarah: Uploaded the Main Street office flyer. 120 Main is still targeting Q3 2026, asking $42/SF.
John: The Union Yard space at 64 Union Yard is available immediately. Around 31k SF, industrial, asking $24/SF.
Priya: Harbor Rd got updated yesterday. 240 Harbor is now 62k SF, not 58k. Use the industrial inventory as source of truth.
Maya: Tenant wants industrial near Main with loading access, ideally under $35/SF and available soon.
Sarah: Added the last-mile watchlist: 18 Beacon Freight is immediate, 36k SF at $26/SF with two dock doors and a real truck court.
John: Tour note: 42 Spruce Flex is under budget and has a small shared yard, but ceiling height is only 20 ft.
Maya: Tenant asked specifically for truck court depth and trailer parking. Beacon and Union Yard are the best in-person fits so far.
Priya: Cold storage at 510 River is real, but availability slipped to September. Good economics, weaker for the near-term logistics brief.
```

## Golden Queries

Use these as README examples, demo prompts, and regression tests.

| Query | Expected Route | Expected Behavior |
| --- | --- | --- |
| `What properties do we have available near 123 Main Street?` | instant | Return 120 Main St and 130 Elm Ave first, sorted by distance, with sources. |
| `Show office buildings under $50/sq ft.` | instant | Return 120 Main St and 17 Pine St, exclude 900 North Loop. |
| `What is the total square footage of industrial properties in John's file or notes?` | instant | Resolve John source and return the deduped John-owned industrial set, including Elm Ave, Beacon, Spruce, and Union Yard. |
| `What do we know about 18 Beacon Freight?` | instant | Return the exact property profile with watchlist, tour-note, and Slack-message sources. |
| `Show industrial listings available soon under $35/SF.` | instant | Apply price and availability filters over the larger industrial set. |
| `What is the average rent for industrial listings under $35/SF?` | instant | Aggregate the deduped industrial set and cite the contributing rows. |
| `Which industrial listings are under $25/SF and available this year?` | instant | Return 88 Foundry Ln, 240 Harbor Rd, 64 Union Yard, and possibly 700 Logistics Pkwy depending date interpretation. |
| `Where did the $42/SF number for 120 Main come from?` | instant | Cite the flyer and Sarah's Slack message if both are indexed. |
| `Summarize the market snapshot and tell me what matters for a logistics tenant.` | agentic | Use Toolhouse path, cite the market PDF and tenant requirements. |
| `Find listings that mention loading access or yard space.` | hybrid | Search chunks/messages and return matching industrial evidence. |
| `Find whse opts with trk court and trlr parking.` | hybrid | Use alias expansion, PolyFuzz, and character n-grams to handle shorthand and typos. |
| `Did anything change for Harbor Rd yesterday?` | hybrid | Use Slack message and CSV freshness to state the square footage correction. |
| `Which options look best for a logistics tenant under $35/SF available soon?` | hybrid | Run the local tenant-fit heuristic before optional Toolhouse review. |
| `What are the best three options for a tenant needing industrial near Main under $35/SF?` | agentic | Retrieve candidates, synthesize trade-offs, cite each recommendation. |
| `Show sources for that answer.` | instant | Return evidence bundle from the previous query. |
| `Why did you use 62k sq ft for Harbor Rd?` | instant | Explain freshness/authority, cite the correction and prior source if present. |
| `Do we have duplicate mentions for 120 Main?` | instant | Group flyer and Slack message evidence under the same property. |

## Evaluation Checklist

### Ingestion

- Historical backfill captures messages.
- Thread replies are fetched separately.
- Files are listed and downloaded.
- Duplicate events do not create duplicate records.
- Extraction status is visible in the database or logs.
- New Slack messages or files can be ingested after startup.

### Extraction

- PDF page references are preserved.
- CSV and XLSX row references are preserved.
- Slack message authors and timestamps are preserved.
- Numeric fields normalize correctly.
- At least one duplicate/conflict is handled conservatively.

### Retrieval

- Exact address lookup works.
- Numeric filters work.
- Aggregations are deterministic.
- Proximity uses coordinates and distance sorting.
- Semantic search finds non-field concepts such as loading access.
- Source authority and freshness affect ranking when records conflict.
- Duplicate property mentions are grouped in the answer.

### Answering

- Every factual answer cites sources.
- No answer invents missing rent, availability, or square footage.
- Slack replies are short and readable.
- `Look deeper` produces a more synthetic answer without losing citations.

## Demo Script

1. Show the local sample import or seeded Slack-shaped records.
2. If live Slack is stable, show the Slack channel with seeded files and messages.
3. Run or mention that backfill/import has completed.
4. Ask the proximity query.
5. Ask the office-under-$50 query.
6. Ask the industrial aggregation query.
7. Click or invoke `Show sources`.
8. Ask the logistics tenant recommendation query.
9. Trigger `Look deeper` and show the Toolhouse-synthesized answer.
10. Show one degraded-mode check, such as structured answers still passing with Qdrant disabled.
11. Close by showing the README architecture diagram and sample queries.

## Minimum Passing Bar

If time gets tight, prioritize these four queries:

1. nearby properties;
2. office under price threshold;
3. industrial square-footage aggregation;
4. one Toolhouse `Look deeper` synthesis.

## Local Import Acceptance

Before live Slack backfill is considered ready, local import should pass this loop:

```text
import_samples -> normalize -> retrieve -> answer_with_citations
```

Acceptance checks:

- every seeded property has a source document;
- every golden answer has at least one evidence item;
- structured queries pass without Qdrant;
- the hybrid query has a keyword fallback if Qdrant is unavailable;
- the Toolhouse handoff receives evidence IDs, not free-floating facts.
- at least one demo answer can be replayed through an answer snapshot or explain-query output.

## Golden Query Test Harness

The sample query table is now executable through both tests and a CLI smoke check:

```bash
uv run cre-cli eval-golden
uv run cre-cli eval-golden --case office_threshold --case harbor_conflict
```

The harness stores fresh answer snapshots, calls `explain_query()` for each query, and verifies:


- expected route is selected;
- expected addresses appear;
- required reason codes appear;
- required source labels are present;
- evidence count meets the case threshold;
- answer snapshot evidence IDs replay in the same order through `explain_query()`;
- expected evidence roles, such as selected/supporting/superseded conflict evidence, are preserved;
- required dependency-state flags match the answer mode.

Use `uv run cre-cli replay-query <query-id>` after any answer or eval case to print the stored answer snapshot, evidence IDs, source details, field-level provenance, dependency state, model versions, replay checks, and saved agent-run traces.

Use `uv run cre-cli demo-doctor --skip-public-callback` before recording to check corpus counts, local dependency health, ingestion quality, golden eval status, and Toolhouse configuration in one non-destructive pass. Drop `--skip-public-callback` when the public Cloudflare URL should also be verified.

Use `uv run cre-cli demo-dry-run --live-toolhouse` for the final recording rehearsal. It executes the expanded video-query sequence, validates replay checks for each answer, and optionally proves the live Toolhouse `Look deeper` path on the loading-access query.

Use `uv run cre-cli submission-report --format markdown --output .runtime/submission-report.md` for the final pre-submission artifact. It combines demo doctor, demo dry run, source secret scan, deliverable paths, and follow-up talking points.
