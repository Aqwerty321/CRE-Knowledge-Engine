---
name: repo-triage
description: Triage repo work by separating structure, memory, web, time, and edit paths. Use at the start of non-trivial repo tasks.
---

## Purpose

Use this skill at the start of non-trivial repo tasks to choose the right retrieval and editing path.

## Triage Checklist

1. Decide whether the task is primarily structural code understanding, prior-context recovery, external documentation lookup, time-sensitive reasoning, or direct implementation in obvious files.
2. Choose the smallest tool path that fits.
3. Keep edits surgical after context is gathered.

## Routing Rules

### Structural

- start with `graphifyLocal_graph_stats` or `graphifyLocal_god_nodes` if you need orientation
- use `graphifyLocal_query_graph` with `bfs` for broad relationship questions
- use `graphifyLocal_query_graph` with `dfs` for narrower dependency or propagation tracing
- use `graphifyLocal_get_node` and `graphifyLocal_get_neighbors` once the entity is known
- use local file reads once the relevant nodes/files are known

### Memory / Continuity

- start with `neo4jMemoryLocal`
- only write back high-signal conclusions

### External Docs

- start with `firecrawlLocal_search` when you want the best results or expect to scrape follow-up pages
- use `searxngLocal_search_web` or `searxngLocal_answer_web` for quick answers or cross-checks
- use `firecrawlLocal_map` when the correct docs page is unclear
- use `firecrawlLocal_scrape` for a known URL and prefer JSON-style extraction for exact fields or lists

### Time Anchoring

- use `timeLocal_get_current_time`, `timeLocal_get_current_date`, or `timeLocal_get_datetime_info` when exact current time matters
- use `timeLocal_format_timestamp` for logs, incidents, deadlines, and schedule translation across timezones

### Direct Edits

- if file paths are obvious, read local files directly first
- do not over-search the repo before making a small obvious fix
