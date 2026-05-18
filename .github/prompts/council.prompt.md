---
name: council
description: Run a five-advisor council on a high-stakes question or tradeoff
argument-hint: "decision or tradeoff"
agent: agent
tools:
  - read
---
Use the `llm-council` skill to pressure-test the user's question or decision.

Return the final verdict with these sections:

- Where the Council Agrees
- Where the Council Clashes
- Blind Spots the Council Caught
- The Recommendation
- The One Thing to Do First
