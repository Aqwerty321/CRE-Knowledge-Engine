---
name: llm-council
description: Run high-stakes questions through five independent advisors, peer review their answers anonymously, and synthesize a final recommendation.
license: MIT
compatibility: opencode
metadata:
  audience: maintainers
  workflow: council
---

## Purpose

Use this skill to pressure-test meaningful decisions with multiple independent perspectives before recommending a course of action.

This skill is agent-agnostic. It assumes the runtime can spawn subagents or equivalent isolated reasoning workers in parallel.

## Use When

- the user asks for a stress test or multiple perspectives
- the decision has real tradeoffs or risk
- the answer depends on judgment, not retrieval alone

Do not use it for:

- factual lookups
- trivial yes/no questions
- straightforward implementation tasks

## Advisors

1. Contrarian: find risks, flaws, and hidden failure modes
2. First Principles Thinker: strip assumptions and reframe from fundamentals
3. Expansionist: identify upside, leverage, and underexplored opportunity
4. Outsider: fresh-eyes perspective with no insider assumptions
5. Executor: focus on speed, practicality, and what to do next

## Workflow

### 1. Frame The Question

- gather the minimum useful context from the user and 2-3 high-signal local files
- prefer `AGENTS.md`, design docs, planning docs, and explicitly referenced files
- rewrite the decision neutrally with stakes and constraints

### 2. Convene The Council

- spawn all 5 advisors in parallel
- give each advisor the same framed question plus their assigned thinking style
- ask for a direct, non-generic response that leans fully into that style

### 3. Peer Review

- anonymize the 5 responses as A-E
- spawn 5 peer reviewers in parallel
- ask which response is strongest, which has the biggest blind spot, and what all responses missed

### 4. Chairman Synthesis

Produce a final answer with exactly these sections:

- Where the Council Agrees
- Where the Council Clashes
- Blind Spots the Council Caught
- The Recommendation
- The One Thing to Do First

### 5. Present The Verdict

- return the verdict directly in chat as Markdown
- do not generate HTML or files unless the user asks

## Output Standard

- be direct
- avoid hedging
- surface real disagreement instead of smoothing it away
- give one clear next step at the end

## Runtime Note

In OpenCode, use whichever subagent path best fits the task and available tools. In other runtimes, use the equivalent subagent or worker mechanism.
