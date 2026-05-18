---
name: mcp-research
description: Use paired MCP workflows for efficient repo and web research. Use when a task spans local files, Graphify, memory, SearXNG, or Firecrawl.
---

## Purpose

Use this skill when the task involves gathering context efficiently across multiple MCP servers.

## Core Pairings

### Firecrawl + SearXNG

For external knowledge:

1. Use `firecrawlLocal_search` first when result quality matters or you expect to scrape follow-up pages.
2. Use `searxngLocal_search_web` or `searxngLocal_answer_web` when a quick answer or shortlist is enough.
3. Use `firecrawlLocal_map` when the correct page inside a docs site is unclear.
4. Use `firecrawlLocal_scrape` for a known URL; prefer JSON-style extraction for fields, parameters, endpoints, and lists.
5. Use `firecrawlLocal_extract` when multiple known URLs should become one structured result.
6. Use `firecrawlLocal_agent` or interactive browser flows only for dynamic, JS-heavy, or multi-step web work.

### Graph + Memory

For repo knowledge:

1. Use `graphifyLocal_graph_stats` and `graphifyLocal_god_nodes` for orientation.
2. Use `graphifyLocal_query_graph` with `bfs` for broad structural questions.
3. Use `graphifyLocal_query_graph` with `dfs` when tracing a narrower dependency or propagation path.
4. Use `graphifyLocal_get_node` and `graphifyLocal_get_neighbors` for focused drilldown.
5. Use `graphifyLocal_shortest_path` for explicit connection questions.
6. Use `graphifyLocal_get_community` when a graph report or wiki points to a promising cluster.
7. Use `neo4jMemoryLocal` for prior decisions, durable facts, and continuity.
8. Combine both when you need to connect a code entity to prior work or decisions.
9. Keep memory repo-scoped and avoid duplicating whole graph structure.

## Efficiency Rules

- Prefer local files when the path is obvious.
- Prefer `graphifyLocal` over grep when the question is structural.
- Prefer `graphify-out/GRAPH_REPORT.md` or `graphify-out/wiki/index.md` when they can answer the question faster than a fresh graph traversal.
- Prefer memory over re-deriving prior decisions.
- Return the minimum useful context.
