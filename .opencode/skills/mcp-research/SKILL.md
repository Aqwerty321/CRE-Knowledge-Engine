---
name: mcp-research
description: Use paired MCP workflows for efficient repo and web research
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: mcp
---

## Purpose

Use this skill when the task involves gathering context efficiently across multiple MCP servers.

## Core Pairings

### Firecrawl + SearXNG

For external knowledge:

1. Use `firecrawl-local_search` first when result quality matters or you expect to scrape follow-up pages.
2. Use `searxng-local_search_web` or `searxng-local_answer_web` when a quick answer or shortlist is enough.
3. Use `firecrawl-local_map` when the correct page inside a docs site is unclear.
4. Use `firecrawl-local_scrape` for a known URL; prefer JSON-style extraction for fields, parameters, endpoints, and lists.
5. Use `firecrawl-local_extract` when multiple known URLs should become one structured result.
6. Use `firecrawl-local_agent` or `firecrawl-local_browser_*` only for dynamic, JS-heavy, or multi-step web work.

### Graph + Memory

For repo knowledge:

1. Use `graphify-local_graph_stats` and `graphify-local_god_nodes` for orientation.
2. Use `graphify-local_query_graph` with `bfs` for broad structural questions.
3. Use `graphify-local_query_graph` with `dfs` when tracing a narrower dependency or propagation path.
4. Use `graphify-local_get_node` and `graphify-local_get_neighbors` for focused drilldown.
5. Use `graphify-local_shortest_path` for explicit connection questions.
6. Use `graphify-local_get_community` when a graph report or wiki points to a promising cluster.
7. Use `neo4j-memory-local` for prior decisions, durable facts, and continuity.
8. Combine both when you need to connect a code entity to prior work or decisions.
9. Keep memory repo-scoped and avoid duplicating whole graph structure.

## Efficiency Rules

- Prefer local files when the path is obvious.
- Prefer `graphify-local` over grep when the question is structural.
- Prefer `graphify-out/GRAPH_REPORT.md` or `graphify-out/wiki/index.md` when they can answer the question faster than a fresh graph traversal.
- Prefer memory over re-deriving prior decisions.
- Prefer subagents for broad exploration, not for final synthesis.
- Return the minimum useful context for the parent agent.

## When To Escalate To Subagents

- Use `explore` for broad read-only repo investigation.
- Use `general` for multi-source research or parallel investigation.
- Keep the parent agent focused on synthesis and edits.
