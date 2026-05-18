# Graphify Notes

## Runtime Pin

This repo currently targets the local Graphify runtime in:

- `/home/Aaditya/venvs/graphify`

Pinned operational version:

- `graphifyy 0.4.12`

## Why 0.4.12

`0.4.12` is the best practical line for this machine and bootstrap setup right now.

Reasons:

- installs cleanly on the current Python 3.14 environment
- includes newer MCP robustness fixes compared with the older `0.4.1` install
- includes better stdio handling, matching, and semantic-preservation behavior than the old install
- avoids the `graspologic` dependency path that currently makes the `v1` line fragile on newer Python versions

## Why Not v1 Right Now

The `v1.0.0` / `v1` line is not the active target here because:

- packaging metadata regresses to `0.1.x`
- it depends on `graspologic`
- that dependency chain is not reliable on this Python 3.14 machine
- the `v1` code path also drops some useful behavior that exists in `0.4.12`

## Local Wrapper Expectations

Even on `0.4.12`, bootstrapped repos may keep local wrapper logic for things upstream does not solve well enough for this workflow:

- empty repo bootstrap fallback graph
- repo-local OpenCode plugin and slash command wiring
- repo-local graph overlay and presentation cleanup
- bootstrap defaults and audit checks

## View Graph Filtering

Presentation outputs may be generated from a filtered view graph.

The raw `graphify-out/graph.json` can keep the full merged graph, while presentation outputs such as `GRAPH_REPORT.md`, `graph.html`, and `wiki/` may intentionally drop low-value nodes that make reports noisy.

This behavior is repo-local and lives in `.opencode/scripts/graphify_repo_overlay.py`.

## Large Repo HTML

The local runtime has been relaxed to allow large HTML graph export attempts instead of failing immediately at the upstream hard node cap.

This does not guarantee the HTML will always be pleasant on very large repos, but it avoids unnecessary hard failure for cases where a large generated HTML artifact is still acceptable.

## Related Docs

- `docs/opencode/mcp-workflows.md`
- `docs/opencode/runtime-notes.md`
