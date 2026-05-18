# MCP Workflows

Use the MCPs in pairs when it reduces token usage and avoids redundant retrieval.

## Search + Scrape

- use `firecrawl-local_search` for primary discovery when you want strong result quality or expect to scrape follow-up pages
- use `searxng-local_search_web` or `searxng-local_answer_web` when a lightweight cited answer or quick cross-check is enough
- use `firecrawl-local_map` when the correct page inside a docs site is unclear
- use `firecrawl-local_scrape` on a known URL; for structured details such as fields, parameters, endpoints, or lists, prefer JSON-style extraction over broad page reads
- use `firecrawl-local_extract` when you already have multiple URLs and want one structured result
- use `firecrawl-local_agent` or `firecrawl-local_browser_*` only for multi-step, JS-heavy, or dynamic-page work that simpler search/map/scrape flows do not handle well

## Graph + Memory

- use `graphify-local_graph_stats` and `graphify-local_god_nodes` for orientation
- use `graphify-local_query_graph` with `bfs` for open-ended structure, topology, and relationship questions
- use `graphify-local_query_graph` with `dfs` when tracing a narrower path or dependency chain
- use `graphify-local_get_node` and `graphify-local_get_neighbors` for focused drilldown on a symbol, command, agent, skill, or MCP
- use `graphify-local_shortest_path` for explicit connection questions
- use `graphify-local_get_community` when a graph report or wiki points to a promising cluster
- use `neo4j-memory-local` for prior decisions, preferences, and continuity
- combine them when a durable conclusion needs to be anchored to a real code entity
- do not duplicate whole code structure into memory

## Time Anchoring

- use `time-local` when the task depends on exact current time, date, local timezone, or timestamp conversion
- use `time-local_get_current_time`, `time-local_get_current_date`, or `time-local_get_datetime_info` to anchor “today”, “now”, maintenance windows, deadlines, or release timing
- use `time-local_format_timestamp` for logs, incidents, cron outputs, and schedule translation across timezones
- prefer `time-local` over inference when time context affects the answer or the quality of the plan

## Frontend Vault + React Bits

- use `frontend-design-vault` for frontend direction: page patterns, composition, visual language, interaction style, spacing/typography heuristics, and design guidance
- use `react-bits-local` for concrete implementation candidates: specific React components, animated sections, backgrounds, cards, navs, and code copy
- for broad frontend build-outs, use them in order:
  1. query `frontend-design-vault` to pick the pattern family and constraints
  2. convert that into 1-3 targeted `react-bits-local_search_components` queries
  3. use `react-bits-local_get_component` only for shortlisted hits
  4. use `react-bits-local_copy_component_variant` only after selection
- for already-concrete component requests, start with `react-bits-local` and only use `frontend-design-vault` if layout or styling guidance is still unresolved
- avoid overlapping retrieval: do not ask both tools the same open-ended prompt
- adapt copied React Bits code to the project’s tokens and visual system instead of importing a mismatched style wholesale

When the graph exists, prefer `graphify-out/GRAPH_REPORT.md` or `graphify-out/wiki/index.md` before broad repo searching if they can answer the question faster.

## Subagent Usage

- use `explore` for broad read-only repo discovery
- use `general` for multi-step or parallel research
- keep the parent agent focused on synthesis and surgical edits
