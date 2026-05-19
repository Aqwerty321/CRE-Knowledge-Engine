# Follow-Up Thread Session And Suggested Questions

Use this file as a Toolhouse Agent File for the `CRE MCP Look Deeper Analyst` worker.

## Purpose

The Slack follow-up UX now has two Toolhouse-facing paths:

- `follow_up_agent`: deeper agent review over a persisted Slack thread session and accumulated backend evidence.
- `suggest_followups`: lightweight generate/refresh task for 3-5 suggested follow-up questions in the Slack modal.

Every answer task (`look_deeper`, `force_agent`, and `follow_up_agent`) also returns next suggested follow-ups in the normal answer JSON. The backend stores those unanswered candidates in `ThreadSession` so the next modal can display useful options immediately without another Toolhouse call.

The backend still owns the source of truth, SQL templates, evidence IDs, citation validation, and Slack posting. Toolhouse may propose question wording and perform deeper analysis, but it must not invent SQL, execute SQL, or create citable evidence outside CRE Backend MCP.

## Slack UX Summary

1. User clicks `Follow Up with Agent ⚡` or uses `follow_up_agent_message_shortcut`.
2. Backend opens the modal immediately and first loads still-relevant unanswered suggestions already cached from prior Toolhouse answer runs.
3. If no cache exists, the modal shows no suggested options and the action button reads `Generate suggestions`.
4. If cached suggestions exist, the same action button reads `Refresh suggestions`.
5. Clicking either button asks Toolhouse for suggested follow-up wording with `task=suggest_followups`; this request is only for question wording, not an answer.
6. Toolhouse returns allowed `{kind, question}` candidates only.
7. Backend merges candidates into the `ThreadSession` suggestion bank, preserves prior unanswered agent-run suggestions, marks answered suggestions when used, attaches prevalidated SQL templates, and ranks the top 4-5 for display.
8. Modal updates with one exclusive follow-up-choice radio group: suggested options plus `Custom question`.
9. A separate radio group controls custom mode: `Instant`, default `Auto`, or `Agent`.
10. If the user chooses a suggestion, the next run is forced to `Instant` mode and resolved by backend-owned prevalidated templates.
11. If the user chooses `Custom question`, the typed prompt uses the selected mode. Backend validation rejects submissions that include both a selected suggestion and custom text.

## `follow_up_agent` Input Shape

The backend sends `task=follow_up_agent` when a custom follow-up needs Toolhouse. The package includes the normal query payload plus these fields:

```json
{
  "task": "follow_up_agent",
  "query_id": "uuid",
  "thread_session": {
    "thread_session_id": "uuid",
    "slack_channel_id": "C123",
    "slack_thread_ts": "1715782000.000200",
    "prior_accumulated_evidence_ids": ["uuid"],
    "query_history": [
      {
        "query_id": "uuid",
        "query_text": "Show office buildings under $50/sq ft.",
        "route_mode": "instant",
        "reason_codes": ["instant", "structured_property_search"],
        "evidence_ids": ["uuid"],
        "evidence_count": 3,
        "role": "answer",
        "mode": "instant"
      }
    ],
    "missing_signals": ["market", "availability"],
    "recommended_mcp_calls": [
      {
        "tool": "search_properties",
        "why": "Find structured property rows covering missing follow-up signals.",
        "arguments": {"filters": {"keywords": ["user follow-up"], "limit": 10}}
      }
    ]
  },
  "follow_up": {
    "parent_query_id": "uuid",
    "requested_mode": "auto",
    "resolution": "new_bundle_needed",
    "coverage": {
      "is_sufficient": false,
      "needs_expansion": false,
      "missing_signals": ["market", "availability"],
      "confidence": "0.2500",
      "evidence_count": 2
    }
  },
  "follow_up_suggestion_context": {
    "allowed_kinds": ["average_rent", "availability_before_q3", "conflict_review", "largest_options", "price_spread"],
    "display_limit": 5,
    "unanswered_suggestions": [
      {
        "id": "stable-short-id",
        "kind": "price_spread",
        "question": "What's the rent spread in this set?",
        "source": "toolhouse_answer",
        "generated_by_query_id": "uuid",
        "generated_at": "2026-05-19T12:00:00+00:00"
      }
    ]
  }
}
```

## `follow_up_agent` Rules

1. Call `explain_evidence(query_id)` first whenever `query_id` exists.
2. Treat `thread_session.query_history` as conversation map, not citable evidence.
3. Treat `thread_session.prior_accumulated_evidence_ids` as backend IDs to verify through MCP before citing.
4. Follow `thread_session.recommended_mcp_calls` unless the user question clearly needs a different backend lookup.
5. If the accumulated bundle already covers the custom question, answer from allowed evidence.
6. If missing signals require new facts, call MCP search/coordinator tools and `expand_query_evidence` before citing.
7. If backend evidence cannot be minted, return `needs_more_evidence` rather than relying on Slack text, memory, or web.
8. Review `follow_up_suggestion_context.unanswered_suggestions` before returning answer-task follow-ups. Keep still-relevant ideas, avoid duplicates, and add only useful next questions.

## Answer-Task Next Follow-Ups

For every `look_deeper`, `force_agent`, and `follow_up_agent` answer, populate `suggested_followups` with 0-5 modal-ready `{kind, question}` objects when useful:

```json
{
  "suggested_followups": [
    {"kind": "price_spread", "question": "What's the rent spread in this set?"},
    {"kind": "largest_options", "question": "Which are the largest options?"}
  ]
}
```

Rules:

- Use only the allowed kinds listed in `follow_up_suggestion_context.allowed_kinds` or the schema.
- Do not include SQL, evidence IDs, IDs, or validation metadata; the backend attaches those.
- Preserve useful unanswered ideas from `follow_up_suggestion_context` by returning them again if still relevant.
- Add new candidates only when the answer naturally creates another useful step.
- It is valid to return an empty array when no next step is useful.

## `suggest_followups` Input Shape

The backend may call Toolhouse with a small package after the user clicks `Generate suggestions` or `Refresh suggestions`:

```json
{
  "task": "suggest_followups",
  "context": {
    "parent_query_id": "uuid",
    "slack_channel_id": "C123",
    "slack_thread_ts": "1715782000.000200",
    "evidence_count": 3,
    "query_history": [
      {
        "query_id": "uuid",
        "query_text": "Show office buildings under $50/sq ft.",
        "route_mode": "instant",
        "evidence_count": 3
      }
    ]
  },
  "allowed_kinds": ["average_rent", "availability_before_q3", "conflict_review", "largest_options", "price_spread"],
  "instructions": "Generate concise CRE follow-up questions. Return only JSON."
}
```

## `suggest_followups` Output Shape

Return only this JSON object for `task=suggest_followups`:

```json
{
  "suggested_followups": [
    {"kind": "average_rent", "question": "What's the average rent for these?"},
    {"kind": "availability_before_q3", "question": "Which have availability before Q3 2026?"},
    {"kind": "conflict_review", "question": "Show me conflicts in this set"},
    {"kind": "largest_options", "question": "Which are the largest options?"},
    {"kind": "price_spread", "question": "What's the rent spread in this set?"}
  ]
}
```

Rules:

- `kind` must be one of `allowed_kinds`.
- Return 3-5 options when possible.
- Keep each `question` short enough for a Slack modal option.
- Do not include SQL in the Toolhouse response.
- Do not cite evidence in this response.
- Do not use the deeper-review output contract for this task.

## Backend-Attached Suggested Follow-Up Shape

After Toolhouse returns allowed kinds, the backend creates the modal option records. These are backend-owned and safe to show/run:

```json
{
  "id": "stable-short-id",
  "kind": "average_rent",
  "question": "What's the average rent for these?",
  "mode": "instant",
  "route_mode": "instant",
  "sql_query": "SELECT AVG(pr.price_per_sq_ft) AS average_price_per_sq_ft ... WHERE ei.id = ANY(:evidence_ids)",
  "sql_params": {"evidence_ids": ["uuid"]},
  "status": "unanswered",
  "generated_at": "2026-05-19T12:00:00+00:00",
  "generated_by_query_id": "uuid",
  "toolhouse_run_id": "toolhouse-run-id",
  "evidence_fingerprint": "short-hash",
  "validation": {
    "status": "prevalidated",
    "executor": "backend_instant_template",
    "raw_sql_execution": false
  },
  "source": "toolhouse_answer"
}
```

Important: the attached `sql_query` is a backend allowlisted template. Toolhouse does not execute it, edit it, or create arbitrary SQL. If a user selects this modal option, the backend ignores the custom mode radio selection and runs the suggestion in `Instant` mode with backend citation validation.

## Allowed Suggestion Kinds

| Kind | Intent | Backend behavior |
| --- | --- | --- |
| `average_rent` | Average asking rent over the current thread bundle | Backend computes from current evidence property records and cites priced evidence. |
| `availability_before_q3` | Options available before Q3 2026 | Backend filters current evidence property records by availability date and cites matches. |
| `conflict_review` | Conflicts inside the current set | Backend checks duplicate groups and differing size/rent/availability values. |
| `largest_options` | Largest options in the current set | Backend sorts current evidence property records by square footage and cites matches. |
| `price_spread` | Lowest-to-highest rent range in the current set | Backend compares priced current evidence property records and cites the low/high records. |

## Failure Behavior

- If no accumulated evidence exists, the backend may show no prevalidated suggestions.
- If Toolhouse is unavailable, the backend may generate local prevalidated suggestions from the same allowed kinds.
- If a selected suggestion is stale or missing, the backend asks the user to choose or type another question.
- Suggested follow-up failures must not block normal custom `Instant`, `Auto`, or `Agent` follow-ups.
- The `Generate suggestions` button appears when no unanswered cached suggestions exist. It forces a new `task=suggest_followups` pass.
- The `Refresh suggestions` button appears after suggestions exist. It also forces a new `task=suggest_followups` pass, while preserving unanswered cached suggestions from previous agent runs and selecting the top current options.
