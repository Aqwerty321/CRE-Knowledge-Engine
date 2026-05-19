# AGENTS

## Repo summary

This workspace is a runnable Slack-native Commercial Real Estate AI agent take-home implementation, with planning docs kept as design history.

The original sources of truth are:

- [problem-statement/Take Home Assigment.txt](problem-statement/Take%20Home%20Assigment.txt)
- [ideation-docs/ideation-part-1.md](ideation-docs/ideation-part-1.md)
- [ideation-docs/ideation-part-2.md](ideation-docs/ideation-part-2.md)
- [ideation-docs/ideation-part-3.md](ideation-docs/ideation-part-3.md)
- [ideation-docs/ideation-part-4.md](ideation-docs/ideation-part-4.md)
- [ideation-docs/ideation-part-5.md](ideation-docs/ideation-part-5.md)
- [ideation-docs/ideation-part-6.md](ideation-docs/ideation-part-6.md)

The implementation-facing sources of truth are now:

- [ideation-docs/ideation-part-7-execution-synthesis.md](ideation-docs/ideation-part-7-execution-synthesis.md)
- [docs/assignment-brief.md](docs/assignment-brief.md)
- [docs/final-implementation-spec.md](docs/final-implementation-spec.md)
- [docs/slack-toolhouse-integration.md](docs/slack-toolhouse-integration.md)
- [docs/cre-data-dictionary.md](docs/cre-data-dictionary.md)
- [docs/retrieval-routing-spec.md](docs/retrieval-routing-spec.md)
- [docs/sample-data-and-evaluation.md](docs/sample-data-and-evaluation.md)
- [docs/architecture-council-review.md](docs/architecture-council-review.md)
- [docs/ambitious-scope-council-review.md](docs/ambitious-scope-council-review.md)
- [docs/first-run-implementation-plan.md](docs/first-run-implementation-plan.md)
- [docs/production-practices.md](docs/production-practices.md)
- [docs/production-practices-council-review.md](docs/production-practices-council-review.md)
- [docs/delivery-plan.md](docs/delivery-plan.md)
- [docs/toolhouse-readiness-checkpoint.md](docs/toolhouse-readiness-checkpoint.md)
- [README.md](README.md)

## Current state

- The repo is scaffolded and now includes `.github/`, `.opencode/`, `docs/opencode/`, `opencode.json`, and `graphify-out/`.
- A runnable FastAPI application is now checked in with Slack event intake, background query and ingestion jobs, local answering, source explanations, broad heuristic structured queries, native PDF/XLSX/CSV/text parsing, optional GLM-OCR image/scanned-document parsing, Qdrant chunk indexing with local embedding/rerank services, demo seeding, live Slack message/file ingestion, thread-aware Slack history backfill, and live Slack demo source sync.
- The refined planning docs now convert the raw ideation into an ambitious MVP build plan, Slack/Toolhouse integration plan, data dictionary, retrieval/routing spec, sample-data plan, architecture council review, scope rebalance, delivery timeline, demo runbook, pre-agent-mode audit, and Toolhouse readiness checkpoint.
- Local `Look deeper` is wired through Slack, queued as a worker job, validated against allowed evidence IDs, and backed by deterministic Toolhouse-facing functions in `app/toolhouse/`.
- The configured MCP entries are Toolhouse and `graphifyLocal`, defined in [.vscode/mcp.json](.vscode/mcp.json).
- `graphify-out/graph.json` exists and was rebuilt on 2026-05-19.
- Verified graph stats: 767 nodes, 1345 edges, 56 communities.
- Current full-suite validation: `uv run pytest -q` passes 100 tests.

## Working guidance

- Prefer local files first when the target is already in the workspace.
- Use Toolhouse docs for integration-specific questions.
- Keep changes small and focused; this repo is still in the planning stage.
- Preserve the original problem statement; add clarified assignment interpretation under `docs/` instead of overwriting the prompt.
- Before implementing runtime behavior, check [docs/production-practices.md](docs/production-practices.md) for P0/P1/P2 priorities, trust invariants, Slack ack/idempotency rules, fallback behavior, and demo-readiness checks. See [docs/production-practices-council-review.md](docs/production-practices-council-review.md) for why those guardrails were chosen.
- Before starting smart agent mode, check [docs/pre-agent-mode-audit-and-next-level-ideas.md](docs/pre-agent-mode-audit-and-next-level-ideas.md) for current implementation status, remaining gaps, and Slack UX direction.
- Before wiring real Toolhouse credentials, check [docs/toolhouse-readiness-checkpoint.md](docs/toolhouse-readiness-checkpoint.md) for the current local boundary, validation invariant, and handoff plan.
- Use `timeLocal` for deadline-sensitive planning, schedule comparisons, or timezone conversions. The assignment deadline in the problem statement is May 20, 2026.

## Intended implementation shape

The ideation docs describe a backend-heavy modular monolith for a Slack AI agent. When implementation starts, keep the major responsibilities separated into ingestion, extraction, normalization, indexing, routing, retrieval, answering, and Toolhouse orchestration.

Prioritize the golden demo path: local sample import, file parsing, structured property records, sourced Slack answers, seeded proximity search, bounded live Slack backfill, continuous message/file ingestion, Qdrant-backed hybrid retrieval, freshness/authority scoring, duplicate grouping, golden query tests, and one Toolhouse `Look deeper` escalation.
