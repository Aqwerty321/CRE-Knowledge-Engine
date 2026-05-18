# Slack Demo Persona Sheet

## Purpose

This sheet defines the human personas used to make the Slack workspace feel like a real CRE team during the demo.

For the exact seeding order and spoken walkthrough, see [slack-demo-runbook.md](slack-demo-runbook.md).

The agent remains the only real bot. The personas are not additional bots. They are fictional teammates whose notes, files, corrections, and requests create the evidence trail the agent answers from.

## Single-User Demo Constraint

If only one real Slack user exists in the workspace, treat the personas as authored voices rather than true Slack identities.

That means:

- messages can be posted manually, seeded with name prefixes such as `Sarah:` or `Priya:`, or seeded with Slack's customized bot username/avatar mode when `chat:write.customize` is enabled;
- files can be uploaded with comments that clearly attribute them to a persona;
- the demo can truthfully show multi-source evidence and persona-specific business context;
- the demo cannot truthfully claim real per-user permissions, identity-aware personalization, or author-visibility enforcement between multiple human users.

If `chat:write.customize` is enabled, prefer customized persona seeds over literal text prefixes for the historical workspace setup, but keep the live answering identity clearly under the real agent bot.

The CLI command for this repo is:

```bash
uv run cre-cli seed-slack-personas --dry-run
```

To refresh older prefixed seed messages into customized persona posts, use:

```bash
uv run cre-cli seed-slack-personas --replace-legacy-prefix
```

Use this framing in the demo:

`The workspace is seeded with teammate personas to simulate realistic internal CRE collaboration. The product behavior being demonstrated is evidence retrieval and source-grounded answering, not enterprise identity management.`

## What You Can Honestly Demo

- source attribution by named teammate voice;
- questions like `What changed for Harbor Rd yesterday?` when the correction message is attributed to Priya;
- questions like `What is the total square footage in John's notes?` if the seeded note clearly says it is from John;
- conflict resolution across spreadsheet facts, field notes, and correction messages;
- channel-scoped retrieval if some material lives in a separate private-demo channel;
- `Show sources` and `Look deeper` behavior.

## What You Should Not Claim

- true user-specific permissions by Slack identity;
- personalized answers based on who asked the question;
- real `John can see this but Maya cannot` behavior;
- live multi-user authorship provenance unless there are actually multiple Slack accounts posting content.

## Channel Model

Use channels for workstreams, not for personas.

Recommended setup:

- `#cre-listings`: listings, field notes, corrections, and tenant-fit discussion;
- `#cre-market-research`: market context, snapshots, tenant requirements, and recommendation inputs;
- `#cre-private-demo`: internal-only notes and private visibility demonstration;
- `#cre-agent-qa`: live questions to the agent during the demo.

## Personas

### Sarah Lin

- Role: Listings manager / broker coordinator
- Voice: concise, polished, commercial
- Typical content: official listing facts, flyer uploads, rent, availability, brochure summaries
- Main channels: `#cre-listings`
- Best use in demo: establish trusted baseline facts for `120 Main St`

Example posts:

- `Sarah: Uploaded the Main Street office flyer. 120 Main is still targeting Q3 2026, asking $42/SF.`
- `Sarah: Downtown office inventory is refreshed. Use the CSV for current office pricing thresholds.`

### John Park

- Role: Field rep / touring associate
- Voice: informal, practical, incomplete but useful
- Typical content: site visit notes, loading access, yard access, timing, rough square footage, operational detail
- Main channels: `#cre-listings`
- Best use in demo: provide unstructured evidence that powers hybrid retrieval

Example posts:

- `John: The Union Yard space at 64 Union Yard is available immediately. Around 31k SF, industrial, asking $24/SF.`
- `John: Elm Ave has one loading dock and usable yard area. Not pretty, but workable for logistics.`

### Priya Raman

- Role: Research / data analyst
- Voice: precise, corrective, source-conscious
- Typical content: spreadsheets, corrections, source-of-truth guidance, market data, fact cleanup
- Main channels: `#cre-listings`, `#cre-market-research`, `#cre-private-demo`
- Best use in demo: create freshness and authority conflicts the agent must resolve correctly

Example posts:

- `Priya: Harbor Rd got updated yesterday. 240 Harbor is now 62k SF, not 58k. Use the industrial inventory as source of truth.`
- `Priya: Tenant requirements summary is attached here for recommendation and look-deeper testing.`

### Maya Chen

- Role: Tenant rep / deal lead
- Voice: problem-oriented, synthesis-seeking
- Typical content: tenant needs, recommendation requests, market context questions, summary asks
- Main channels: `#cre-market-research`, `#cre-listings`
- Best use in demo: trigger the agent's recommendation and synthesis flows

Example posts:

- `Maya: Tenant wants industrial near Main with loading access, ideally under $35/SF and available soon.`
- `Maya: Uploaded the Q2 metro market snapshot and retail brief for market context and demand signals.`

## Demo Seeding Pattern

For a single-user workspace, seed content in this order:

1. Sarah posts a flyer and one polished listing update.
2. John posts one messy field note.
3. Priya posts one spreadsheet-backed correction.
4. Maya posts one tenant requirement.
5. Add one reply thread under Priya's correction.
6. Upload the relevant files with comments attributing them to the same personas.

This creates a believable evidence story without needing multiple real Slack users.

## Recommended Live Demo Flow

1. Show `#cre-listings` and explain that the workspace is seeded with teammate personas.
2. Ask a direct question such as `Show office buildings under $50/sq ft.`
3. Ask a hybrid question such as `Find listings that mention loading access or yard space.`
4. Ask a conflict question such as `Why did you use 62k sq ft for Harbor Rd?`
5. Click `Show sources`.
6. Ask a synthesis question such as `What are the best three options for a tenant needing industrial near Main under $35/SF?`
7. Trigger `Look deeper` when that path is ready.

## Suggested Spoken Framing

Use wording like this during the demo:

`This workspace is seeded with realistic teammate personas so the agent has to reason over the kinds of evidence a real CRE team shares: flyers, spreadsheets, field notes, corrections, and tenant requests. The thing being tested here is grounded retrieval and source-aware answering, not a production identity model.`
