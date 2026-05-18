# Retrieval And Routing Spec

## Routing Goal

Choose the cheapest reliable answer path for each Slack question.

The router should not be a giant `if` chain. It should produce a score and reason codes that can be logged, debugged, and tuned.

## Modes

| Mode | Use When | Output |
| --- | --- | --- |
| `instant` | Structured facts are enough. | Direct answer from PostgreSQL with citations. |
| `hybrid` | Structured filters plus semantic evidence are needed. | Ranked evidence from PostgreSQL and Qdrant. |
| `agentic` | Query is ambiguous, subjective, broad, or user clicked `Look deeper`. | Toolhouse synthesis over retrieved evidence. |

## Router Signals

Positive signals for `instant`:

- exact address or file reference;
- numeric threshold such as `under $50` or `over 10,000 sq ft`;
- aggregation words such as `total`, `count`, `average`, `sum`;
- property type keywords;
- explicit source reference such as `John's file` or `the spreadsheet`;
- temporal window that maps to stored timestamps.

Positive signals for `hybrid`:

- partial address or fuzzy location phrase;
- multiple constraints plus natural-language context;
- query references document content rather than known fields;
- exact filters narrow the search but do not fully answer it.

Positive signals for `agentic`:

- subjective terms such as `best`, `interesting`, `risky`, `good fit`;
- broad summary request;
- ambiguous target market or user intent;
- multi-hop comparison across sources;
- explicit `Look deeper` action;
- low retrieval confidence after hybrid search.

## Suggested Scoring

Start with a simple additive score:

| Signal | Route Bias | Points |
| --- | --- | --- |
| Numeric constraint found | instant | +3 |
| Aggregation word found | instant | +3 |
| Exact address match | instant | +4 |
| Property type found | instant | +2 |
| Date window found | instant | +1 |
| Source/uploader reference | instant | +2 |
| Fuzzy location phrase | hybrid | +2 |
| Summary verb | agentic | +3 |
| Subjective adjective | agentic | +3 |
| Multiple evidence sources needed | hybrid | +2 |
| User clicked `Look deeper` | agentic | +10 |
| Missing required extracted field | agentic | +2 |

Initial decision rule:

- choose `instant` if instant score is at least 5 and higher than agentic score by 2 or more;
- choose `agentic` if agentic score is at least 5 or `Look deeper` was clicked;
- otherwise choose `hybrid`.

The thresholds should be tuned against the golden query set.

## Query Classes

### Exact Lookup

Example: `What do we know about 120 Main St?`

Route: `instant` if address matches normalized records.

Behavior: return the freshest grouped property record and source list.

### Numeric Filter

Example: `Show office buildings under $50/sq ft.`

Route: `instant`.

Behavior: SQL filter on `property_type = office` and `price_per_sq_ft < 50`.

### Aggregation

Example: `What's the total square footage of industrial properties in John's file?`

Route: `instant`.

Behavior: resolve source reference, filter records by source/uploader, sum `sq_ft` deterministically.

### Proximity

Example: `What properties are available near 123 Main Street?`

Route: `instant` for seeded addresses, `hybrid` if location phrase is fuzzy.

Behavior: resolve anchor coordinate, compute Haversine distance, sort by distance plus source quality.

### Fuzzy Document Search

Example: `Which listings mention loading docks or yard space?`

Route: `hybrid`.

Behavior: semantic search chunks, then join matching chunks to property records.

### Synthesis

Example: `Which available industrial options look most promising for a logistics tenant?`

Route: `agentic`.

Behavior: retrieve candidate records, package evidence, ask Toolhouse to synthesize within the facts.

## Retrieval Stack

Structured retrieval is the core reliability path. Hybrid retrieval is part of the full demo path and should power at least one golden query, but exact lookup, numeric filters, aggregation, proximity, source lookup, and citations must work from PostgreSQL even if Qdrant is unavailable.

### Structured Retrieval

Use PostgreSQL for:

- filters;
- aggregations;
- exact address matching;
- source filtering;
- freshness sorting;
- provenance joins.

### Keyword Retrieval

Use PostgreSQL text search or lightweight keyword matching for:

- exact phrases;
- file names;
- uploader names;
- addresses;
- terms like `loading dock`, `yard`, `sublease`.

### Semantic Retrieval

Use Qdrant for:

- fuzzy phrasing;
- document context;
- broad summaries;
- soft concepts such as `recent market commentary`.

For the MVP, Qdrant only needs to prove one or two hybrid paths. Good candidates are:

- `Find listings that mention loading access or yard space.`
- `Summarize the market snapshot and tell me what matters for a logistics tenant.`

If Qdrant is unavailable, fall back to keyword search over stored chunks and keep structured answers working.

### Authority, Freshness, And Duplicate Grouping

Use lightweight scoring to make answers feel CRE-aware:

- fresher inventory rows outrank older duplicate flyers when the facts conflict;
- CSV/XLSX inventories generally outrank casual Slack messages for numeric fields;
- Slack corrections can outrank older structured files when the correction explicitly references the property;
- deterministic extraction outranks low-confidence semantic extraction;
- duplicate mentions should be grouped by normalized address, property type, and source recency.

Do not implement full canonical entity resolution in the MVP. Group duplicates for answer presentation and cite the sources that agree or conflict.

### Reranking MVP

Combine scores with a transparent formula:

```text
final_score =
  0.40 * semantic_score +
  0.25 * structured_match_score +
  0.15 * source_authority_score +
  0.10 * freshness_score +
  0.10 * extraction_confidence
```

For purely structured queries, semantic score can be omitted.

## Negative Retrieval Behavior

If no result is found:

- say that no matching sourced property was found;
- mention the filters applied;
- offer closest related sources if confidence is acceptable;
- do not fabricate a listing;
- include `Look deeper` only if broader semantic search may help.

Example:

```text
I could not find a sourced office listing under $35/sq ft in the indexed files. Closest match: 17 Pine St, $48/sq ft, from Downtown Office Inventory.csv row 4.
```

## Citation Rules

Each answer must cite at least one evidence item unless it is an explicit system-status response.

Preferred order:

1. file name or Slack message source;
2. page or row;
3. poster/uploader;
4. posted date;
5. Slack link when available.

## Confidence Labels

Keep visible labels subtle:

- `Direct match` for instant answers;
- `Expanded search` for hybrid answers;
- `Deeper review` for Toolhouse answers.

Do not show internal route scores by default.

## Golden Query Priority

The router should be tuned against the sample-data golden queries before generalized routing is expanded.

Priority order:

1. nearby properties from seeded coordinates;
2. office properties under a rent threshold;
3. industrial square-footage aggregation;
4. source lookup for a specific rent or square-footage fact;
5. one hybrid concept query;
6. one Toolhouse `Look deeper` synthesis.

This keeps the router accountable to demo behavior instead of abstract score elegance.

The golden query harness should run these checks automatically against the sample dataset before recording the demo.
