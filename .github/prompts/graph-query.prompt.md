---
name: graph-query
description: Query the repo-local Graphify graph for a broad structural question
argument-hint: "question"
agent: agent
tools:
  - graphifyLocal/*
---
Use `graphifyLocal_query_graph` with:

- `question`: the user's argument text
- `mode`: `bfs`
- `depth`: `3`
- `token_budget`: `1800`

Then summarize:

- the core nodes and edges that answer the question
- the highest-signal files or repo entities to inspect next
- whether `get_node`, `get_neighbors`, `get_community`, or `shortest_path` would sharpen the answer
