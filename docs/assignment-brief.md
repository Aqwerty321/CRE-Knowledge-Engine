# Assignment Brief

## Original Goal

Build a working prototype of a Slack AI agent for a Commercial Real Estate team. The agent should ingest Slack messages and shared files, understand property information, and answer natural-language questions with sourced responses.

The original assignment is preserved in [problem-statement/Take Home Assigment.txt](../problem-statement/Take%20Home%20Assigment.txt).

## Required User Outcomes

The agent must help CRE teammates answer questions such as:

- What properties are available near a given address?
- Which office buildings are under a target rent threshold?
- What is the total square footage of industrial properties in a file someone posted?
- Where did a fact come from?
- What changed or appeared in Slack recently?

## Hard Requirements

- Ingest designated Slack channels, including historical content.
- Continue ingesting new messages and file uploads.
- Parse PDFs, CSVs, Excel files, and text content.
- Use AI where it adds value, but keep factual filters and arithmetic deterministic.
- Answer in Slack with accurate sources.
- Include a clear GitHub repo structure.
- Include setup and run instructions in the eventual deliverable README.
- Include sample test queries and expected behavior.
- Include a simple architecture diagram.
- Include a Slack demo video.
- Submit by May 20, 2026.

## Practical Acceptance Criteria

The take-home should be considered complete when the demo can show:

1. A configured Slack channel has sample messages and property files.
2. The backend can backfill the channel and ingest visible files.
3. New messages or files can be ingested after startup.
4. Extracted facts appear in the structured store with provenance.
5. Chunks appear in semantic search with metadata.
6. A direct structured query returns a short answer and sources.
7. A price or square-footage filter returns correct rows.
8. An aggregation query computes exact totals from structured records.
9. A proximity query returns nearby properties using seeded coordinates.
10. A deeper synthesis query goes through Toolhouse or a Toolhouse-style agent path.
11. The bot can show or link to original Slack/file sources.

## What Matters Most To Evaluators

The prompt says clean, thoughtful implementation and a working prototype matter more than a perfect production system. That implies the strongest submission should prioritize:

- reliable ingestion over fancy answer prose;
- correct citations over broad unsupported synthesis;
- deterministic math and filters over LLM guessing;
- clear architecture boundaries over too many services;
- a controlled, realistic demo dataset over random scraped files;
- a crisp trade-off story for the follow-up call.

## Non-Goals For The Prototype

These are valuable, but should not block the first working version:

- full enterprise permission modeling;
- OCR for scanned brochures;
- external geocoding APIs;
- complex entity resolution across all duplicates;
- a review UI for uncertain extraction;
- production-grade monitoring dashboards;
- Kubernetes or distributed microservices.

## Follow-Up Call Themes

Be ready to discuss:

- the hardest part: getting reliable extraction, provenance, and Slack ingestion to work together;
- two-week improvements: OCR, geocoding, better entity resolution, stronger reranking, source authority, and review workflows;
- trade-offs: deterministic reliability versus agent flexibility, prototype speed versus production depth, and calm UX versus explainability.
