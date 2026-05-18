---
name: repo-research
description: Use the repo-local MCP research workflow on a specific query
argument-hint: "repo question"
agent: agent
tools:
  - read
  - grep
  - graphifyLocal/*
  - neo4jMemoryLocal/*
  - searxngLocal/*
  - firecrawlLocal/*
---
Research the user's repo-specific question efficiently using local files, Graphify, Neo4j memory, SearXNG, and Firecrawl as appropriate.

Return:

- the chosen retrieval path
- the highest-signal findings
- the smallest next context to load
