---
name: project-bootstrap
description: Orient a freshly bootstrapped repo to the local MCP workflow and scaffolded files
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: bootstrap
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
6. Inspect `opencode.json` and confirm `graphify-local` points at the current repo's graph artifacts.
7. Verify `.gitignore` includes generated artifact paths.
8. If the project is frontend-heavy, confirm whether `react-bits-local` and `frontend-design-vault` are available and reflected in the repo’s instructions.
9. If `time-local` is available globally, decide whether the repo guidance should mention it for logs, deadlines, schedules, timezone conversions, or other time-sensitive workflows.

## Working Rules

- Prefer local files first when the target path is obvious.
- Use `graphify-local` for structure and relationship questions.
- Use `neo4j-memory-local` for durable prior decisions and preferences.
- Use `time-local` when the task depends on exact current time, date, timezone conversion, or readable timestamp formatting.
- Use `firecrawl-local` and `searxng-local` only for external docs or current web information.
- Keep repo-specific instructions in `AGENTS.md`; do not leave the generic template unchanged.

For frontend-oriented repos, encode this routing rule in the repo-local guidance:

- `frontend-design-vault` decides frontend direction: pattern family, visual language, motion level, and composition
- `react-bits-local` supplies concrete component implementations, full component docs, and code copy
- use them sequentially, not redundantly: direction first, implementation second
- do not import React Bits into an established design system unless it fills a real missing primitive

## Recommended Follow-Up

- run `/graph-report` for fast graph orientation
- run `/mcp-audit` to confirm scaffold health
- use `repo-triage` for the first non-trivial task in the repo
- use `mcp-research` when a task spans graph, memory, and web retrieval
- if `time-local` is available, document its productive uses such as log correlation, incident timing, schedule planning, and timezone-aware deadlines
- for frontend repos, document whether agents should prefer `frontend-design-vault`, `react-bits-local`, or both for UI build-out tasks
