---
description: Find the shortest graph path between two repo concepts using `left | right` arguments
---
Interpret `$ARGUMENTS` as `source | target`.

If the separator is missing, ask for arguments in that format.

If both sides are present, call `graphify-local_shortest_path` with:

- `source`: the trimmed text on the left side
- `target`: the trimmed text on the right side
- `max_hops`: `8`

Then explain:

- the path in plain language
- which files or nodes make the connection important
- whether `get_neighbors` on an intermediate node would be useful next
