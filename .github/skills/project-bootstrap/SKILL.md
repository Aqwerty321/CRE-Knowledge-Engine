---
name: project-bootstrap
description: Orient a freshly bootstrapped repo to the local MCP workflow and scaffolded files. Use when opening a new or newly bootstrapped repo.
---

## Purpose

Use this skill in newly bootstrapped repos to understand what the scaffold added, what still needs repo-specific customization, and how to start working effectively.

## What Bootstrap Provides

Expect these files and directories to exist after bootstrap:

- `AGENTS.md`
- `GRAPHIFY_NOTES.md`
- `docs/opencode/mcp-workflows.md`
- `docs/opencode/runtime-notes.md`
- `.opencode/agents/*`
- `.opencode/skills/*`
- `.opencode/commands/*`
- `.opencode/scripts/*`
- `opencode.json`

## First-Run Checklist

1. Read `AGENTS.md` and replace generic project summary text with repo-specific reality.
2. Confirm the MCP inventory matches the repo's configured MCPs.
3. Read `docs/opencode/mcp-workflows.md` and `docs/opencode/runtime-notes.md`.
4. Check whether `graphify-out/graph.json` exists.
5. If the graph is missing or stale, run the local graph build path.
6. If `timeLocal` is available, decide whether the repo guidance should mention it for logs, deadlines, schedules, timezone conversions, or other time-sensitive workflows.

## Working Rules

- Prefer local files first when the target path is obvious.
- Use `graphifyLocal` for structure and relationship questions.
- Use `neo4jMemoryLocal` for durable prior decisions and preferences.
- Use `timeLocal` when the task depends on exact current time, date, timezone conversion, or readable timestamp formatting.
- Use `firecrawlLocal` and `searxngLocal` only for external docs or current web information.
