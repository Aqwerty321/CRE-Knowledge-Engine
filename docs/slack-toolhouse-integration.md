# Slack And Toolhouse Integration Spec

## Research Notes

Slack Events API docs emphasize a few implementation constraints that should shape this project:

- event requests should receive a 2xx response within 3 seconds;
- slow work should be queued after acknowledgement;
- Slack retries failed deliveries up to three times, roughly immediately, after 1 minute, and after 5 minutes;
- retry headers include `x-slack-retry-num` and `x-slack-retry-reason`;
- Events API delivery is capped around 30,000 events per workspace, per app, per 60 minutes;
- Web API rate limits are per method, per workspace, per app;
- `HTTP 429` responses include `Retry-After` and should be honored;
- posting messages should generally stay near 1 message per second per channel;
- cursor pagination must be followed to avoid partial backfills.

Local Toolhouse Slack tool lists confirm that the Slackbot integration exposes the primitives this prototype needs:

- `SLACKBOT_LIST_CONVERSATIONS`;
- `SLACKBOT_FETCH_CONVERSATION_HISTORY`;
- `SLACKBOT_FETCH_MESSAGE_THREAD_FROM_A_CONVERSATION`;
- `SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK`;
- `SLACKBOT_DOWNLOAD_FILE`;
- `SLACKBOT_SEARCH_ALL`;
- `SLACKBOT_SEARCH_MESSAGES`;
- `SLACKBOT_UPDATES_A_MESSAGE`.

Toolhouse docs frame workers as agents with integrations and attached knowledge files. For this project, that maps best to an agentic escalation worker that can use Slack and backend retrieval tools, while the backend remains the system of record.

## Ambitious MVP Contract

The implementation should prove the evidence pipeline locally before it depends on live Slack or Toolhouse.

Build order:

1. local sample import with Slack-shaped metadata;
2. deterministic extraction and PostgreSQL evidence storage;
3. structured Slack answers from stored evidence;
4. bounded live Slack backfill for one to three configured channels;
5. continuous new message and file ingestion;
6. Qdrant-backed hybrid retrieval;
7. one Toolhouse `Look deeper` path with backend retrieval tools;
8. source authority, freshness, and duplicate grouping polish.

The local importer and live backfill must share the same source-document, file, extraction, and evidence contracts.

## Recommended Ownership Model

### Slack Bolt Backend

Use Slack Bolt for deterministic event intake:

- verify Slack requests;
- acknowledge quickly;
- enqueue ingestion and query jobs;
- handle interactive button payloads;
- post and update deterministic answers;
- preserve idempotency and checkpoints.

### Toolhouse Worker

Use Toolhouse for deeper agent behavior:

- `Look deeper` synthesis;
- broad summaries over retrieved evidence;
- ambiguous questions requiring judgment;
- optional Slack worker integration for demo polish;
- calling backend tools instead of directly inventing facts.

This keeps the prototype Toolhouse-native without making the core data pipeline depend on agent reliability.

Do not run both Slack Bolt and Toolhouse as competing Slack-facing agents in the MVP. Slack Bolt should own event intake and deterministic replies. Toolhouse should appear through `Look deeper` or a single deeper query path.

## Slack App Configuration

### Recommended Events

Subscribe only to events needed for the demo:

- `app_mention` for questions to the bot;
- `message.channels` for public-channel ingestion;
- `message.groups` if private-channel ingestion is needed;
- `file_created` or `file_shared` for file intake;
- interactive actions for `Look deeper` and `Show sources` buttons.

### Recommended Scopes

Exact scopes depend on bot versus user-token choices, but the app will likely need:

- `app_mentions:read`;
- `channels:read` and `channels:history`;
- `groups:read` and `groups:history` if private channels are used;
- `files:read`;
- `chat:write`;
- `users:read` for source display names;
- `commands` only if slash commands are added.

For a demo workspace, prefer one public channel to reduce permission friction.

## Historical Backfill Plan

Backfill must be explicit because the assignment requires historical data.

0. First, support local sample import that writes Slack-shaped `channel`, `ts`, `user`, file, and permalink-like metadata.
1. Read configured channel IDs from environment or database.
2. For each channel, call conversation history with a cursor.
3. Store each message with Slack `channel`, `ts`, `user`, `text`, and raw payload hash.
4. If a message has thread metadata, call the thread replies endpoint with the parent `thread_ts`.
5. Call file listing by channel and time range.
6. Download each visible file by file ID.
7. Store file metadata and content pointer.
8. Enqueue extraction jobs.
9. Persist `next_cursor`, oldest/latest windows, and completion state.

Important detail: channel history does not return thread replies as full conversation history. Threads need their own fetch step.

MVP scope is bounded, not fake: support one to three configured channels well, including messages, thread replies, file listing, file download, checkpoints, and idempotency. Avoid workspace-wide administration or complex permission modeling.

## Continuous Ingestion Plan

For new events:

1. Receive event payload.
2. Verify request signature.
3. Dedupe by Slack event ID and source ID.
4. Acknowledge within 3 seconds.
5. Enqueue work by event type.
6. Fetch full message or file detail if payload is partial.
7. Extract, normalize, index, and record provenance.

If Slack retries an event, idempotency should make the duplicate harmless.

New message and file ingestion is part of the ambitious MVP, not a stretch goal. It is the fastest way to show that the agent can learn from newly posted Slack knowledge.

## File Handling

File metadata and content should be separated:

- Slack file ID;
- file name;
- MIME type;
- size;
- uploader;
- channels;
- created timestamp;
- source URL or permalink;
- local path or object storage key;
- content hash;
- extraction status.

`SLACKBOT_LIST_FILES_WITH_FILTERS_IN_SLACK` returns metadata only. A separate download step is required before parsing.

## Interaction Flow

### Direct Answer

1. User mentions the bot.
2. Backend receives the event and queues query handling.
3. Router selects instant or hybrid mode.
4. Backend posts a threaded answer with sources.
5. The message includes buttons for `Show sources` and `Look deeper` when useful.

### Look Deeper

1. User clicks `Look deeper`.
2. Backend records the action and packages the original query, route decision, evidence bundle, and evidence-context manifest.
3. Toolhouse worker receives the grounded context and may call backend tools for schema guidance, source detail, aggregation, chunk search, proximity, and controlled evidence expansion.
4. Backend updates the existing thread with the expanded answer.

### Show Sources

1. User clicks `Show sources`.
2. Backend returns the source list, including file name, page or row, sender, posted date, and Slack link.
3. Use an ephemeral response or threaded reply depending on Slack support and demo needs.

### Broaden Search

Optional if time allows:

1. User clicks `Broaden search`.
2. Backend relaxes filters or enables hybrid semantic retrieval.
3. Bot updates the thread with expanded evidence while keeping original filters visible.

## Rate Limit Behavior

Backfill and indexing should use conservative rate handling:

- always follow cursors;
- honor `Retry-After`;
- retry idempotent reads with backoff;
- avoid bursty message updates;
- store progress after every page;
- resume from the last saved checkpoint.

For the demo, keep the workspace small enough that rate limits do not dominate the story.

## Queue Contract

Start with PostgreSQL-backed jobs rather than Redis or Celery.

Minimum worker behavior:

- insert a job before expensive work starts;
- atomically claim queued jobs;
- record attempts and last error;
- store Slack cursor, file, page, or row checkpoints;
- make retries idempotent by source document and content hash;
- leave enough job state to explain ingestion progress during debugging.

Add Redis/RQ/Celery only if the implementation needs it for speed after the local import and golden queries are working.

## Toolhouse Tool Surface

Toolhouse should call backend tools rather than inspect the database directly.

Ambitious MVP tools:

- `describe_backend_schema`;
- `summarize_inventory`;
- `rank_properties`;
- `get_property_timeline`;
- `find_property_conflicts`;
- `search_properties`;
- `aggregate_properties`;
- `search_source_chunks`;
- `get_source_detail`;
- `nearby_properties`;
- `expand_query_context`;
- `expand_query_evidence`;
- `explain_evidence`.

The agent should receive evidence IDs and source summaries, then return a synthesis that the backend formats through the same citation layer. If a Toolhouse search or coordinator call finds useful backend context that was not part of the original allowed evidence set, the agent should call `expand_query_evidence` or pass `query_id` to a query-aware coordinator tool before citing it. The backend then refreshes allowed IDs during response validation.

## Failure Modes

| Failure | Expected Behavior |
| --- | --- |
| Slack event retry | Dedupe and skip already processed event. |
| File download fails | Mark source as failed and expose retry command. |
| Parser fails | Keep source record, mark extraction status, and still index any recoverable text. |
| Qdrant unavailable | Answer structured queries from PostgreSQL and label semantic search as unavailable internally. |
| Toolhouse unavailable | Keep instant and hybrid answers working; hide or disable `Look deeper`. |
| Rate limited | Pause the affected method/workspace and resume from checkpoint. |
