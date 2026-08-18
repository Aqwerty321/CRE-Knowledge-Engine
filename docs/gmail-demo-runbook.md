# Gmail CRE demo — build and Toolhouse runbook

This is a standalone demo path. It does not start the existing application and does not require PostgreSQL, Qdrant, Slack, or Zapier.

## What is implemented

The standalone backend lives in [`gmail_demo/`](../gmail_demo/). It exposes nine Toolhouse MCP tools:

1. `describe_demo_contract`
2. `get_seed_properties`
3. `validate_listing_event`
4. `validate_property_delete`
5. `validate_requirement_event`
6. `search_property_knowledge`
7. `match_requirement`
8. `compose_requirement_reply`
9. `compose_property_query_reply`

Google Sheets remains the only demo database. Toolhouse owns the Gmail/Sheets actions. The backend validates data, performs BM25 lexical retrieval over the supplied Sheet rows, applies deterministic matching rules, and authorizes a reply payload only for the exact test sender and `[CRE-DEMO]` thread; Toolhouse's Gmail tool performs the send. This path does not use embeddings or a reranker.

## 1. Create the empty Google Sheet

Create one spreadsheet named `CRE Gmail Demo`.

1. Rename the first blank worksheet to exactly `Properties`.
2. Add one blank worksheet named exactly `ProcessedEmails`.
3. Copy the spreadsheet ID from this part of its URL:

```text
https://docs.google.com/spreadsheets/d/SPREADSHEET_ID/edit
```

Do not import a CSV or paste property data. On its first run, the Toolhouse Worker writes both header rows and calls `get_seed_properties` to create exactly 30 synthetic Austin property rows. It refuses to auto-seed a partially populated sheet.

## 2. Start the standalone backend

The local secret file is [`.env.gmail-demo`](../.env.gmail-demo) and is ignored by Git. For a fresh checkout, create it from the committed template:

```bash
cp .env.gmail-demo.example .env.gmail-demo
```

Fill these values in that file:

| Variable | What to enter |
| --- | --- |
| `GMAIL_DEMO_PRIMARY_EMAIL` | Keep `aaditya@toolhouse.ai` |
| `GMAIL_DEMO_SECONDARY_EMAIL` | Keep `aadityasoni2020@gmail.com` |
| `GMAIL_DEMO_MCP_TOKEN` | Output of `openssl rand -hex 24` |
| `GMAIL_DEMO_PUBLIC_URL` | The Cloudflare public HTTPS origin, without `/toolhouse/mcp` |
| `GMAIL_DEMO_SECONDARY_APP_PASSWORD` | The secondary Gmail's 16-character Google App Password |
| `TOOLHOUSE_API_KEY` | API key from Toolhouse |
| `GMAIL_DEMO_TOOLHOUSE_CHAT_ID` | Deployed `https://agents.toolhouse.ai/...` URL, or a raw Agent Studio Chat UUID |
| `GMAIL_DEMO_SPREADSHEET_ID` | ID between `/d/` and `/edit` in the Google Sheet URL |
| `GMAIL_DEMO_SENDER_NAME` | The signature name, currently `Aaditya` |

Validate the file without printing any values:

```bash
uv run --env-file .env.gmail-demo gmail-demo-check
```

Do not continue until it prints `Gmail demo environment is ready`.

This workstation already has a dedicated named tunnel configured:

- public origin: `https://gmail-cre.aqwerty321.me`
- ingress: `gmail-cre.aqwerty321.me` → `http://127.0.0.1:8030`
- tunnel config: `~/.cloudflared/gmail-cre-demo.yml`
- persistent services: `gmail-cre-demo-backend.service` and `gmail-cre-demo-tunnel.service`

Both services are enabled under the user systemd manager. Manage them with:

```bash
systemctl --user restart gmail-cre-demo-backend.service gmail-cre-demo-tunnel.service
systemctl --user status gmail-cre-demo-backend.service gmail-cre-demo-tunnel.service
```

Verify it locally:

```bash
curl http://127.0.0.1:8030/health
```

Expected response:

```json
{"status":"ok","database":"google_sheets","orchestrator":"toolhouse"}
```

The Toolhouse MCP URL is:

```text
https://gmail-cre.aqwerty321.me/toolhouse/mcp?token=VALUE_OF_GMAIL_DEMO_MCP_TOKEN
```

Do not paste the token into screenshots, chat, or committed files. For a fresh machine without these services, the backend can still be started manually with `uv run --env-file .env.gmail-demo python -m gmail_demo`.

## 3. Create the Toolhouse Worker

Create one private Toolhouse Worker. Connect only these three capabilities:

### Gmail

Connect the receiving demo inbox. Enable tools that can:

- search/list Gmail messages by label or Gmail query;
- read a message and its conversation/thread;
- read message ID, thread ID, sender, subject, timestamp, body, and attachments;
- inspect replies already sent in a thread;
- send a reply in an existing thread.

The Worker prompt restricts sending to one reply addressed to `aadityasoni2020@gmail.com` for an eligible `[CRE-DEMO]` requirement. Do not connect any production or customer inbox for this demo.

### Google Sheets

Connect the account that can edit `CRE Gmail Demo`. Enable tools that can:

- read worksheet rows;
- find rows by field value;
- create rows;
- update rows;
- delete one exact row by a validated `property_id`.

### Custom MCP

Add the public MCP URL from step 2. Confirm that Toolhouse discovers exactly the nine `Gmail CRE Demo MCP` tools listed above.

## 4. Configure the Worker

1. Copy the system prompt from [`toolhouse-gmail-demo-agent-prompt.md`](toolhouse-gmail-demo-agent-prompt.md). This controlled demo version intentionally hardcodes the test spreadsheet ID and sender name.
2. Publish the Worker privately.
3. Confirm that Agent Studio discovers Gmail, Google Sheets, and the nine custom MCP tools.
5. Copy the deployed `https://agents.toolhouse.ai/...` URL. Create a Toolhouse API key for the live trigger. The sender accepts this URL directly; a raw Agent Studio Chat UUID also works.

The live sender still passes `spreadsheet_id` and `sender_name` as Agent Run variables for backward compatibility, but the current prompt does not depend on them. Republish the current prompt before testing CRUD; an older published prompt does not contain the DELETE or property-query workflows.

Toolhouse Scheduled Runs currently have a ten-minute minimum cadence, so this demo does not pretend that a one-minute schedule exists. The live seeder creates an immediate Agent Run after each delivered email and waits for it to complete before sending the next message. A ten-minute Scheduled Run can be added later as a recovery poll.

## 5. Exact account topology

- **Primary monitored inbox:** `aaditya@toolhouse.ai`
- **Secondary live sender:** `aadityasoni2020@gmail.com`
- **Toolhouse Gmail connection:** connect only `aaditya@toolhouse.ai`
- **Worker query:** `from:aadityasoni2020@gmail.com subject:"[CRE-DEMO]"`
- **Reply result:** sent from `aaditya@toolhouse.ai`, inside the final requirement thread, to `aadityasoni2020@gmail.com`

No Gmail label, Gmail filter, Slack connection, Zapier connection, `.eml` import, or connection to the secondary inbox is required.

## 6. Enable the real Gmail sender

On the secondary account, enable Google 2-Step Verification and create a Gmail App Password. Put only that App Password in `GMAIL_DEMO_SECONDARY_APP_PASSWORD` inside `.env.gmail-demo`; never use the account's normal password and never commit the value. Add the Toolhouse API key and shared Chat ID to the same file.

Google documents App Password creation at [Sign in with app passwords](https://support.google.com/accounts/answer/185833). If the option is unavailable, use manual sending for the demo or replace SMTP with OAuth; do not provide the normal Gmail password to this program.

First prove what will be sent without connecting to Gmail:

```bash
uv run --env-file .env.gmail-demo python -m gmail_demo.seed --dry-run
```

Then send only message 1 as a live smoke test:

```bash
uv run --env-file .env.gmail-demo python -m gmail_demo.seed --confirm-live-send --trigger-toolhouse --limit 1
```

That single command performs the first visible loop: deliver message 1, wait eight seconds for Gmail, start a Toolhouse Agent Run, wait for the run to complete, seed the empty Sheet, update the matching property, and write the Gmail message ID to `ProcessedEmails`.

After verifying the smoke test, send messages 2–10:

```bash
uv run --env-file .env.gmail-demo python -m gmail_demo.seed --confirm-live-send --trigger-toolhouse --start-at 2
```

The sender opens a real authenticated Gmail SMTP session, adds a unique Gmail message ID plus demo run/sequence headers, and sends each message to the primary inbox. It never writes to the Sheet. After delivery it calls Toolhouse's official Agent Runs API and polls the returned run ID until Toolhouse reports `completed`; only then does it send the next email. If a run fails, the sequence stops so you can fix it and resume with `--start-at N`.

## 7. What happens live

Expected progression:

- The first Agent Run seeds the 30-row property database automatically.
- Messages 1–8 arrive in the real primary inbox and update the matching property rows.
- Message 9 changes Atlas Flex Campus Suite 100 from `$21.00` to `$21.75` and from `1,600A` to `1,800A` without creating a duplicate row. Listing writes always preserve/resolve the suite's stable `property_id` and use only that ID as the Sheet upsert key.
- Message 10 triggers a read of all property rows, BM25 retrieval plus deterministic FIT/UNKNOWN/NO_FIT matching, and one real reply sent in the original Gmail thread.
- Divisible listings are presented as the compatible configuration (for example, `16,000 SF within a 32,000 SF suite`) rather than falsely presenting the full suite as the proposed size.
- Equivalent requirements such as `existing clean room` plus `needs_clean_room=true` produce one check and one caveat, not duplicates.
- The legal-footer address in message 2 never becomes a property.
- Every successful message appears once in `ProcessedEmails`.

## 8. Live demo script

Keep these four screens open:

1. The initially empty `Properties` worksheet, then the automatic jump to 30 rows.
2. `aaditya@toolhouse.ai` receiving `[CRE-DEMO]` messages in real time.
3. The Toolhouse run log showing Gmail read → CRE MCP validation/matching → Sheet update.
4. The final requirement thread showing the ranked-property reply sent automatically from the primary account.

Use this narration:

> The secondary account is acting as the market. These are real Gmail messages arriving live. Each delivery triggers a real Toolhouse Agent Run. The Worker ignores anything outside our exact sender-and-subject query, uses our backend to validate and match CRE facts, keeps the property database in Google Sheets, and sends one grounded response back to the secondary account when the requirement arrives. Nothing in this sequence is reading a local email file or pretending to receive mail.

## Local verification

```bash
uv run pytest -q tests/test_gmail_demo.py
```

The standalone backend does not need Docker services for these tests.
