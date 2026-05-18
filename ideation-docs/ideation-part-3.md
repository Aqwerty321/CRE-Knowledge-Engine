# Ideation — Part 3

## What this document is for

This document captures the rest of the decisions that matter for the project but were not fully spelled out yet. It is the “make it real” layer: operational choices, user experience details, demo strategy, edge cases, trade-offs, and the important things that are easy to forget when thinking only in architecture terms.

The guiding idea stays the same:

**build a quiet, sharply intelligent Slack-native CRE engine that answers simple questions immediately, escalates only when needed, and always feels trustworthy.**

---

## The product in one sentence

A Slack agent for commercial real estate teams that can read messages and files, extract property facts, answer questions from structured and semantic retrieval, and escalate to a deeper agentic pipeline only when the question truly needs it.

---

## The final product character

The product should feel like a highly competent analyst that does not try too hard.

It should not feel like:
- a chatbot roleplaying intelligence
- a loud AI assistant narrating itself
- a flashy demo with fake thinking animations
- a platform trying to impress with complexity

It should feel like:
- calm
- fast
- precise
- observant
- slightly understated
- quietly better than expected

That personality is part of the product, not just a UI choice.

---

## What the system should be good at

The system should be excellent at six things:

### 1) Reading Slack content
It should continuously ingest:
- messages
- replies
- file uploads
- older historical content in selected channels

### 2) Understanding attachments
It should be able to parse:
- PDFs
- CSVs
- Excel files
- text files
- plain Slack messages

### 3) Turning messy CRE data into usable facts
It should extract and normalize:
- addresses
- property type
- square footage
- price per square foot
- availability
- dates
- poster / author
- source file and page / row references

### 4) Answering simple questions instantly
If the answer is obvious and structured, the system should not waste time calling the LLM.

### 5) Escalating when the query is genuinely complex
If the question is vague, broad, subjective, or synthesis-heavy, the system should use the full Toolhouse agent pipeline.

### 6) Explaining where the answer came from
Every answer should be grounded in sources, not just language fluency.

---

## The interaction model

The user should have three broad ways to interact with the bot:

### Auto mode
This is the default. The system decides whether the query can be answered heuristically, whether it needs retrieval, or whether it should escalate.

### Force agent mode
This is for power users or ambiguous queries that the user already knows are better handled with deeper reasoning.

### “Look deeper” escalation
This is the best UX pattern for the project. The user gets an instant answer, then can click a subtle button to send the question into the agentic pipeline if the quick answer is not enough.

This is the most elegant compromise between speed and intelligence.

---

## The user experience details that matter

### Keep the Slack surface calm
The answer should be short, useful, and not show too much of the plumbing.

Good:
- direct answer
- source references
- small action buttons
- small mode label if needed

Not good:
- loud AI animation
- verbose progress narration
- pipeline dumps
- “thinking…” theatrics
- overly transparent internal reasoning

### The right tone
The bot should sound like:
- a competent teammate
- not a mascot
- not a salesman
- not an overexcited assistant

### The right visual style
Use very subtle labels such as:
- Direct match
- Expanded search
- Look deeper
- Show sources

These are enough. Do not overdecorate.

---

## What the heuristic system should feel like

The heuristic layer should feel almost invisible.

It should handle:
- exact matches
- numeric filtering
- aggregations
- direct lookup
- source lookups
- common property-type queries
- date-based queries
- simple proximity logic if available

The best heuristic answer is one that feels obvious after the fact.

If the system gets a question like:
- “What is the total square footage of industrial properties in John’s file?”
it should answer directly without pretending to reason deeply.

That is where the “insanely intelligent” feeling comes from: the system knows when the answer is straightforward.

---

## What the agentic layer should feel like

The deeper Toolhouse pipeline is not the default personality. It is the fallback for nuanced or uncertain questions.

Use it for:
- subjective recommendations
- summarizing multiple documents
- interpretation across several uploads
- broad questions that do not map neatly to structured fields
- ambiguous asks where a heuristic answer would be too shallow

The agentic layer should feel like the bot quietly went and checked more context, not like it dramatically entered a cinematic reasoning state.

---

## Slack features that are worth building

These are the Slack features that make the project feel like a real product rather than a script.

### 1) Threaded replies
Keep the main channel clean.

### 2) Action buttons
The most important one is **Look deeper**. Others can be:
- Show sources
- Broaden search
- Retry with more context

### 3) Small status metadata
A tiny footer such as “Direct match” or “Expanded search” is enough if you want to hint at the route taken.

### 4) Message updates
If a response is being refined or escalated, update the same Slack message instead of posting a noisy chain.

### 5) Source previews
Let the user see which file, message, page, or row supported the answer.

### 6) Optional ephemeral or threaded confirmations
These are useful when a query is being processed or a user action has been accepted.

### 7) A “not satisfied” escalation path
This is one of the most important product ideas in the whole project. It makes the system resilient to routing mistakes and gives users control.

---

## What to avoid in Slack

Avoid:
- fake “AI is thinking” messages
- overly verbose execution traces
- raw prompt dumps
- chain-of-thought style disclosures
- aggressive branding around intelligence

The whole point is to feel sharp without trying to prove it.

---

## The routing philosophy in plain english

The router should answer one question first:

**Can this be answered confidently from structured data and simple rules?**

If yes, answer immediately.

If no, ask:
**Can retrieval solve this with evidence?**

If yes, use structured + semantic retrieval.

If still no, or if the query is vague or synthesis-heavy, hand it to the Toolhouse agent.

That is the cleanest possible mental model.

The key idea is not “use the LLM less” just for the sake of it. The key idea is:
- use the cheapest reliable path first
- use deeper reasoning only when it adds real value

---

## What “smart” means for this system

In this project, smart does not mean “always using the model.”

Smart means:
- knowing when the answer is already in the data
- knowing when retrieval is enough
- knowing when the question is too fuzzy for deterministic handling
- not pretending certainty where there is none

That is what makes the system feel intelligent.

---

## The missing architectural piece: provenance

This is easy to forget, but it matters a lot.

Every extracted fact should keep track of:
- where it came from
- who posted it
- when it was posted
- whether it came from a PDF, CSV, Excel file, or message
- which page or row supported it

This is what lets the bot answer follow-up questions like:
- “Where did that come from?”
- “Was that from the spreadsheet or the PDF?”
- “Show me the original source”

If provenance is weak, the entire system feels shaky.

---

## The missing operational piece: reprocessing and replay

The system should not behave like a one-way pipe.

If the extraction gets better later, you should be able to:
- reprocess historical content
- reindex documents
- rebuild the retrieval layer
- rerun normalization on old data

That matters because the sample data and the final demo will likely improve during development.

A good pipeline is replayable.

---

## The missing quality piece: deduplication

The same property information may appear:
- in a PDF
- in a spreadsheet
- in a Slack message
- in a reposted attachment
- in a thread reply

Without deduplication, the system will look confident but noisy.

Deduplication should happen at ingestion time and should consider:
- file hashes
- message hashes
- channel / timestamp combinations
- repeated rows or identical listings

This is one of those boring details that quietly protects the whole product.

---

## The missing intelligence piece: structured extraction quality

The project gets much better if extraction is not just “text out.”

At minimum, the system should try to recognize:
- address
- property type
- size
- rent or price
- availability status
- date
- market or location
- source author
- source file name

Even if the extraction is imperfect, the attempt itself makes the system much more useful.

This is the difference between:
- searching documents
and
- understanding CRE content

---

## The missing retrieval piece: exact + semantic together

The retrieval strategy should not be one thing.

It should combine:
- exact matching for addresses, prices, filenames, and dates
- semantic search for fuzzy phrasing and context
- structured filters for numeric and categorical constraints

That combination is what makes the system feel robust.

A pure vector search engine is too vague for CRE.
A pure rule engine is too brittle for human language.

You need both.

---

## The missing UX piece: confidence without overexplanation

The system can show a tiny hint about how it answered, but it should not become a lecture.

Good:
- Direct match
- Expanded search
- Look deeper

Also good:
- a very small confidence or source hint if useful

Not good:
- a full reasoning transcript
- excessive mode labels
- a giant list of internal steps

The product should imply intelligence, not narrate it.

---

## The missing user control piece

The user should not be trapped by the router.

If the instant answer is not enough, the user should have a way to say:
- look deeper
- broaden search
- show sources
- answer with more context

This protects the system from imperfect routing and gives advanced users a way to steer it.

This also makes the product feel cooperative rather than rigid.

---

## The missing data design piece: two representations of the same content

Every source item should ideally exist in two forms:

### Unstructured representation
Used for:
- semantic retrieval
- contextual reading
- fuzzy matches
- broad summarization

### Structured representation
Used for:
- filtering
- counts
- sums
- comparisons
- exact lookups

This dual representation is one of the strongest design decisions in the whole project.

It lets the system behave like both a search engine and a database-backed analyst.

---

## The missing trade-off discussion

There are real trade-offs in this design.

### Trade-off 1: Simplicity vs intelligence
A smaller system is easier to build. A richer routing system feels smarter. The sweet spot is not maximalism; it is selective intelligence.

### Trade-off 2: Heuristics vs LLM flexibility
Heuristics are fast and reliable for structured questions, but they can miss nuance. The LLM is flexible, but expensive and less deterministic. The project works best when each is used where it is strongest.

### Trade-off 3: Transparency vs calm UX
You could expose everything the system is doing, but that usually makes the product feel noisy and amateurish. A subtle UX feels more mature.

### Trade-off 4: Narrow scope vs impressive ambition
The architecture can support a lot more than the demo needs. The key is not to implement every possibility just because the architecture is capable of it.

### Trade-off 5: Backend depth vs shipping speed
This is a backend-heavy project by design, but that should not become an excuse to overbuild infra that the assignment does not need.

---

## The missing deployment decision

Do not use Minikube for this assignment.

The right choice is a Docker Compose setup with a modular monolith and background workers.

That gives you:
- easy local reproducibility
- lower debugging overhead
- a clean README
- fewer moving parts
- a more reliable demo

Kubernetes is a future concern, not a take-home necessity.

---

## The missing demo strategy

The demo should tell a simple story:

1. Slack messages and files are ingested.
2. The bot can answer direct questions immediately.
3. The bot can show sources.
4. The user can click “Look deeper” when they want more context.
5. The deeper path can synthesize across multiple files and messages.
6. The system stays calm and useful throughout.

The demo does not need to show every feature.
It needs to show:
- reliability
- sourcing
- routing
- escalation
- utility

That is enough to impress.

---

## The missing sample data strategy

The sample data should look realistic, not synthetic in a way that feels fake.

Use:
- a few PDFs with property sheets
- a couple CSV inventories
- one or two Excel sheets
- some Slack-style text messages
- overlapping mentions of the same properties across formats

The sample set should create a believable knowledge base with enough overlap for the system to show off retrieval and deduplication.

---

## The missing evaluation strategy

You should be able to say whether the system is working.

Useful success signals:
- the bot retrieves the right source most of the time
- simple questions are answered instantly
- the deeper mode gets used only when it adds value
- citations are correct
- the demo questions return grounded answers

This is more important than absolute model cleverness.

---

## The missing “what would I improve with two more weeks” story

This question will probably come up, so it helps to already know the answer.

The best follow-up improvements would be:

- better geospatial search
- stronger entity extraction
- more sophisticated reranking
- OCR fallback for scanned documents
- richer source linking
- better uncertainty handling
- more robust historical backfill
- a small internal review UI
- richer analytics on query patterns
- better entity deduplication across channels

That gives you a very strong answer in the follow-up conversation.

---

## The missing future-facing improvements

If the project had more time later, the best improvements would be:

- a richer knowledge graph over properties, brokers, and markets
- automatic clustering of listings by area or segment
- better cross-document merging of duplicate properties
- smarter confidence scoring
- more advanced answer synthesis
- per-user or per-team preferences
- analytics on commonly asked questions
- better handling of scanned or image-only attachments

These are future enhancements, not first-week essentials.

---

## The missing naming and presentation point

The project name should sound calm and credible, not gimmicky.

The brand should suggest:
- source-grounded intelligence
- clarity
- trust
- retrieval
- property knowledge

The name should not scream “AI toy.”

The README should reinforce that tone with:
- a simple architecture overview
- clear setup instructions
- realistic example queries
- a clean demo narrative
- a short explanation of the heuristic-first escalation model

---

## The missing quality bar for the final answer style

The bot’s answers should generally:
- be short
- mention the matching properties or records
- include the relevant source references
- avoid speculation
- admit when the answer is partial
- offer deeper search only when needed

The system should sound helpful without sounding chatty.

---

## The missing internal logging and debugging view

Even if the user never sees it, you should log:
- query type
- route taken
- confidence
- retrieval candidates
- response latency
- escalations
- whether the user clicked deeper later

That will help you debug routing decisions and explain trade-offs later.

---

## The missing safety and reliability posture

This is not a safety-heavy project in the usual sense, but it still needs careful behavior.

The system should:
- avoid inventing facts
- distinguish between evidence and inference
- avoid overclaiming when the data is incomplete
- keep source references attached to claims
- prefer “I found” over “I know” when the answer comes from retrieved evidence

That makes the system much more believable.

---

## The overall architecture, in one paragraph

The final design is a Docker Compose modular monolith in Python with FastAPI, Slack integration, PostgreSQL for structured truth, Qdrant for semantic retrieval, a worker for ingestion and embedding jobs, a heuristic router for instant answers, and Toolhouse as the agent shell for deeper reasoning. The Slack interface stays understated and calm, with a subtle escalation path like “Look deeper” that moves a query from deterministic retrieval into the agentic pipeline when the user wants more context.

---

## Final summary

The important decisions now are all in place:

- backend-heavy but not overboard
- Docker Compose monolith, not Kubernetes
- heuristic-first answer routing
- instant answer mode for structured questions
- agentic mode for ambiguous or synthesis-heavy queries
- Toolhouse as orchestration shell, not data store
- Postgres for structured truth
- Qdrant for semantic retrieval
- strong extraction and normalization
- subtle Slack UX
- user-controlled escalation
- quiet competence as the product vibe

That is the real system.

