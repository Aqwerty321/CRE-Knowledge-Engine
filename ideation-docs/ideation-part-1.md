# Ideation — Part 1

## Project direction

Build a Slack-native AI agent for Commercial Real Estate (CRE) that can ingest messages and files, extract property knowledge, and answer questions with sources.

The system should feel like a **quietly excellent knowledge engine**, not a flashy chatbot. It should answer simple questions immediately when confidence is high, and escalate to deeper retrieval / Toolhouse agent reasoning only when needed.

---

## Core product philosophy

1. **Heuristic-first, LLM-last**
   - Use deterministic rules and structured queries for obvious questions.
   - Use retrieval + reranking for medium-complexity questions.
   - Use the Toolhouse agent for ambiguous, multi-hop, or synthesis-heavy queries.

2. **Quiet competence over transparent theatrics**
   - Do not over-explain internal reasoning in Slack.
   - Keep the UI subtle and confident.
   - Show only enough metadata to build trust (sources, recency, maybe a small mode label).

3. **Structured truth + semantic search**
   - Store CRE facts in a relational database.
   - Store embeddings in a vector database.
   - Use both; do not rely on embeddings alone.

4. **Progressive escalation**
   - Start with instant deterministic answers.
   - Offer a user-controlled escalation path for deeper analysis.
   - Add a “look deeper” style action in Slack to route the query into the agentic pipeline.

---

## Final architecture decisions

### 1) System shape
Use a **backend-heavy modular monolith** with Docker Compose, not Kubernetes and not a microservice sprawl.

The code should be organized like separable internal modules, but run as a small set of services locally.

### 2) Toolhouse role
Toolhouse should be the **orchestration / agent shell**, not the place where the actual knowledge lives.

Use Toolhouse for:
- Slack-facing agent behavior
- tool calling / orchestration
- agentic fallback
- scheduled jobs / backfills if useful
- interaction with external integrations via MCP

Keep the core CRE logic in your own backend:
- ingestion
- parsing
- normalization
- indexing
- retrieval
- ranking
- citations
- structured aggregations

### 3) Answer routing
The system should support **three modes**:

- **Auto**: router chooses heuristic vs retrieval vs agentic path.
- **Force Agent**: skip heuristics and go straight to Toolhouse reasoning.
- **Force Heuristic**: deterministic / instant path only.

For the Slack UX, the best version is not a manual command first — it is a subtle escalation button on the heuristic response, such as **“Look deeper”**.

### 4) Slack UX tone
The interface should feel:
- casual
- nonchalant
- intelligent
- low-noise
- not cheesy

Avoid obvious “AI is thinking” theatrics. Prefer subtle labels like:
- `Direct match`
- `Expanded search`
- `Look deeper`
- `Show sources`

---

## The intended intelligence model

The system should behave like a **nonchalant, insanely capable retrieval engine**.

### Instant answer mode
Use when the question is obvious and structured.
Examples:
- total square footage
- under / over a threshold
- specific property type
- source lookup
- simple aggregation
- direct listing retrieval

### Agentic answer mode
Use when the question is vague, subjective, multi-source, or requires synthesis.
Examples:
- best-fit recommendations
- summary of uploaded material
- broad market interpretation
- ambiguous “what should I care about” questions

### Escalation UX
If an instant answer is good but not sufficient, the user can click **“Look deeper”** to send the original query, heuristic result, and retrieval context into the Toolhouse agent pipeline.

This is the preferred way to resolve uncertainty without overusing the LLM.

---

## Query routing decisions

The router should use a **score-based heuristic system**, not just a giant if/else chain.

Suggested signals:
- property type keywords
- numeric constraints (`under $50`, `> 10k sq ft`)
- aggregation words (`total`, `sum`, `count`, `average`)
- temporal references (`yesterday`, `last month`, `Q3 2026`)
- proximity words (`near`, `within`, `around`)
- source references (`John posted`, `in the PDF`, `yesterday's spreadsheet`)
- ambiguity level / semantic fuzziness

Routing outcomes:
- **Heuristic answer** if confidence is high
- **Hybrid retrieval** if structure + evidence is needed
- **Toolhouse agent** if the query is ambiguous or synthesis-heavy

---

## Data and retrieval architecture

### Storage plane
Use separate stores for different purposes:

1. **PostgreSQL**
   - source documents
   - messages
   - extracted property records
   - normalized fields
   - timestamps
   - provenance
   - ingestion state
   - answer/evidence logs

2. **Qdrant**
   - embeddings
   - chunk search
   - metadata filtering

3. **Optional keyword / text search**
   - can live in Postgres for the prototype
   - useful for exact address / price / filename matching

### Knowledge representation
Every source item should ideally exist in two forms:

- **Unstructured**: raw / chunked text for semantic retrieval
- **Structured**: normalized property facts for filters and aggregations

This dual representation is one of the key design decisions.

---

## Extraction and normalization decisions

### Inputs to support
- Slack messages
- PDFs
- CSVs
- Excel files
- simple text attachments

### Extraction approach
- PDFs: use PyMuPDF first
- CSV/XLSX: use pandas + openpyxl
- text messages: preserve sender, timestamp, channel, and links

### Normalize aggressively
Extract and standardize:
- addresses
- prices / currency values
- square footage
- property type labels
- availability dates
- filenames
- source references

This is what makes numeric and filter-based questions reliable.

---

## Slack UX decisions

### Good UX primitives
- Slack threaded replies
- message updates
- buttons for escalation
- buttons for sources / broader search
- context blocks for small metadata hints

### Best interaction pattern
1. User asks a question.
2. Bot returns a quick deterministic answer if possible.
3. If the user wants more depth, they click **Look deeper**.
4. The agentic pipeline runs and updates the thread with a broader answer.

### Tone
- concise
- confident
- professional
- not performative
- not verbose

### What to avoid
- giant execution traces
- obvious chain-of-thought exposition
- “thinking…” theatrics
- overly loud mode labels

---

## Tech stack decision

### Language
- **Python**

### Backend framework
- **FastAPI**

### Slack integration
- **Slack Bolt for Python**

### LLM / orchestration
- **Toolhouse** as the agent shell and escalation layer

### Parsing
- **PyMuPDF** for PDFs
- **pandas** for CSV/XLSX
- **openpyxl** for Excel

### Databases
- **PostgreSQL** for structured truth and provenance
- **Qdrant** for vector retrieval
- **Redis** only if a queue/cache is needed

### Background jobs
- **Celery** or a lightweight equivalent if needed for parsing/indexing jobs

### Deployment
- **Docker Compose**
- no Minikube
- no Kubernetes for the take-home

---

## Repo / code structure decision

A modular monolith layout is the right fit:

```text
app/
├── slack/
├── ingestion/
├── extraction/
├── normalization/
├── enrichment/
├── indexing/
├── retrieval/
├── answering/
├── planner/
├── db/
└── utils/
```

This gives strong separation without the pain of real microservices.

---

## Slack response style decisions

When answering in Slack, the bot should:
- show the result first
- cite the source second
- offer subtle follow-up actions
- keep the formatting clean

Example tone:
- `Found 3 matches.`
- `Expanded search found 2 more related listings.`
- `Look deeper`
- `Show sources`

This is intentionally understated.

---

## What belongs in the “two more weeks” bucket

These are valuable, but not necessary for the first working prototype:
- geospatial search / address geocoding
- advanced reranking models
- confidence scoring dashboards
- OCR fallback for scanned PDFs
- richer provenance UI
- replayable event-sourcing pipeline
- analytics / admin UI
- broader entity resolution across sources
- more advanced query planning

These are the right answers for the follow-up question about what you would do with more time.

---

## Name direction

Best project naming direction so far:
- **GroundTruth CRE**
- **PropertyLens**
- **Atlas CRE**

The strongest overall brand direction is **GroundTruth CRE**, because it matches the source-grounded, evidence-first nature of the system.

---

## Final product summary

This project should be a Slack-native CRE intelligence engine that:
- ingests Slack messages and files
- extracts property facts
- stores both structured and semantic representations
- answers simple queries instantly
- escalates ambiguous queries into Toolhouse agent mode
- keeps the UX subtle, sharp, and trustworthy

The core principle is:

> **Deterministic first, intelligent when needed, invisible when possible.**

