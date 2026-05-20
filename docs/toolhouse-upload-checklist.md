# Toolhouse Upload Checklist

Use this checklist for the manual Toolhouse website update.

## Copy/Paste Sources

- System prompt to paste: [docs/toolhouse-system-prompt.md](toolhouse-system-prompt.md)
- Agent Files to upload: [docs/toolhouse-agent-files/01-cre-backend-mcp-tool-contract.md](toolhouse-agent-files/01-cre-backend-mcp-tool-contract.md), [docs/toolhouse-agent-files/02-cre-data-dictionary.md](toolhouse-agent-files/02-cre-data-dictionary.md), [docs/toolhouse-agent-files/03-trust-citation-readiness-rules.md](toolhouse-agent-files/03-trust-citation-readiness-rules.md), [docs/toolhouse-agent-files/04-sample-query-package.json](toolhouse-agent-files/04-sample-query-package.json), [docs/toolhouse-agent-files/05-required-output-schema.json](toolhouse-agent-files/05-required-output-schema.json), [docs/toolhouse-agent-files/06-local-readiness-notes.md](toolhouse-agent-files/06-local-readiness-notes.md), [docs/toolhouse-agent-files/07-follow-up-thread-session-and-suggestions.md](toolhouse-agent-files/07-follow-up-thread-session-and-suggestions.md)

## Website Configuration

1. Paste the full prompt from [docs/toolhouse-system-prompt.md](toolhouse-system-prompt.md) into the Toolhouse system-prompt field.
2. Upload all seven Agent Files from [docs/toolhouse-agent-files](toolhouse-agent-files).
3. Confirm the MCP server is attached as `CRE Backend MCP`.
4. Set the MCP URL to `https://<public-backend-host>/toolhouse/mcp` or `https://<public-backend-host>/toolhouse/mcp?mcp_token=<CRE_TOOLHOUSE_MCP_BEARER_TOKEN>` when Toolhouse only exposes a URL field.
5. Use `Authorization: Bearer <CRE_TOOLHOUSE_MCP_BEARER_TOKEN>` if the Toolhouse MCP UI supports auth headers.

## Enable Only These Supporting Integrations

- Agent Files
- Code Interpreter
- Semantic Memory Search
- Memory (remember)
- Web Search
- Newswire
- Metascraper
- File Download
- Document Parser
- Describe Image
- Page Screenshot
- Slackbot read-only tools

## Keep Disabled

- Slack write/admin/upload/delete/archive/schedule actions
- Worker Email
- Toolhouse Schedules
- Image generation/editing
- Any direct database access path

## Post-Upload Verification

1. Keep the backend and tunnel running.
2. Restore the live demo corpus if tests were run:

```bash
uv run cre-cli sync-slack-demo-sources --recent-limit 250
uv run cre-cli sync-slack-history --recent-limit 250 --reindex
```

1. Run the current live smoke:

```bash
uv run cre-cli toolhouse-smoke "Show properties with cap rate over 5.5%."
```

1. Success condition:

- `validation.valid` is `true`
- `cited_evidence_ids` is non-empty when the answer is factual
- `toolhouse_fallback` is `false`

## Current Reason For Refresh

The backend MCP contract and uploaded local docs are current, but the last hosted Toolhouse smoke still returned `parse_error: empty_response`, which caused backend fallback. The prompt and readiness files were tightened so the worker is explicitly told to emit one non-empty JSON object even on failure. Re-uploading the website configuration is the right next step.
