---
name: mcp-audit
description: Audit whether the repo-local OpenCode scaffolding and Graphify wiring are present
agent: agent
tools:
  - terminal
  - read
---
Run the shell command `./.opencode/scripts/audit-opencode` and summarize any missing files, missing instructions, or Graphify wiring gaps.
