---
name: MCP Routing
description: Tool routing guidance for the common local MCP stack.
applyTo: "**"
---
# MCP routing guidance

- Choose tools by information type instead of by habit.
- Use repo files directly when the target path is obvious.
- Use `graphifyLocal` for structure, topology, relationships, graph drilldown, and named repo entities.
- Use `neo4jMemoryLocal` for durable decisions, preferences, prior conclusions, and continuity.
- Use `timeLocal` for exact current time/date, timezone conversion, timestamp formatting, deadline anchoring, incident timelines, and time-aware planning.
- Use `firecrawlLocal` for primary external discovery when result quality matters, for known-URL scrape, map, structured extraction, agentic web research, and browser flows.
- Use `searxngLocal` for quick cited answers, lightweight narrowing, and web cross-checks.
- Use `playwrightLocal` for deterministic browser interaction, UI verification, and reproduction of interactive web flows.

## Preferred order

For repo-internal work:

1. Read obvious local files directly.
2. Use `graphifyLocal` when structure or relationships matter.
3. Use `neo4jMemoryLocal` when past context may matter.
4. Use `timeLocal` when the task depends on exact current time, local timezone, or readable timestamp conversion.
5. Use web MCPs only for external docs or current information.

For external API or library work:

1. Use `firecrawlLocal_search` when you want the best current result set or expect follow-up scraping.
2. Use `searxngLocal_search_web` or `searxngLocal_answer_web` when a quick answer or shortlist is enough.
3. Use `firecrawlLocal_map` when the correct page inside a docs site is unclear.
4. Use `firecrawlLocal_scrape` for a known URL and prefer structured extraction for exact fields, parameters, endpoints, or lists.
5. Use `firecrawlLocal_extract` when you already know multiple URLs and want one structured result.
6. Use `firecrawlLocal_agent` or interactive browser flows only when simpler search/map/scrape paths are insufficient.
