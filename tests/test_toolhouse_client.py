from __future__ import annotations

from app.toolhouse.client import build_toolhouse_message, is_acceptable_live_toolhouse_outcome, parse_toolhouse_response_payload


def test_parse_toolhouse_response_payload_accepts_plain_json() -> None:
    payload, error = parse_toolhouse_response_payload('{"status":"answered","rendered_answer":"ok"}')

    assert error is None
    assert payload == {"status": "answered", "rendered_answer": "ok"}


def test_parse_toolhouse_response_payload_accepts_fenced_json() -> None:
    payload, error = parse_toolhouse_response_payload('```json\n{"status":"mcp_unavailable"}\n```')

    assert error is None
    assert payload == {"status": "mcp_unavailable"}


def test_parse_toolhouse_response_payload_extracts_json_from_stream_text() -> None:
    payload, error = parse_toolhouse_response_payload('chunk 1\n{"status":"answered","cited_evidence_ids":[]}\nchunk 2')

    assert error is None
    assert payload == {"status": "answered", "cited_evidence_ids": []}


def test_build_toolhouse_message_preserves_query_package_shape() -> None:
    message = build_toolhouse_message(
        {
            "status": "ready",
            "query_id": "query-1",
            "allowed_evidence_ids": ["evidence-1"],
        }
    )

    assert '"task": "look_deeper"' in message
    assert '"query_id": "query-1"' in message
    assert "Use CRE Backend MCP first" in message
    assert "If the initial evidence bundle is empty" in message
    assert "return needs_more_evidence or external_context_only" in message
    assert "Keep rendered_answer terse and aligned with the backend instant-answer style" in message
    assert "comparison_table object" in message
    assert "return suggested_followups as 0 to 5 short" in message
    assert "Do not include SQL in suggested_followups" in message


def test_build_toolhouse_message_marks_force_agent_task() -> None:
    message = build_toolhouse_message(
        {
            "status": "ready",
            "query_id": "query-1",
            "reason_codes": ["force_agent", "instant_router_skipped"],
            "allowed_evidence_ids": [],
        }
    )

    assert '"task": "force_agent"' in message
    assert "the user intentionally bypassed instant routing" in message


def test_build_toolhouse_message_marks_follow_up_agent_task() -> None:
    message = build_toolhouse_message(
        {
            "status": "ready",
            "query_id": "query-1",
            "reason_codes": ["follow_up", "follow_up_agent", "new_bundle_needed"],
            "allowed_evidence_ids": ["evidence-1"],
            "thread_session": {
                "prior_accumulated_evidence_ids": ["evidence-1"],
                "missing_signals": ["location"],
                "recommended_mcp_calls": ["cre_search_evidence"],
            },
            "follow_up_suggestion_context": {
                "unanswered_suggestions": [
                    {"kind": "price_spread", "question": "What's the rent spread for the current set?"}
                ]
            },
        }
    )

    assert '"task": "follow_up_agent"' in message
    assert "prior_accumulated_evidence_ids" in message
    assert "recommended MCP calls" in message
    assert "follow_up_suggestion_context" in message
    assert "What's the rent spread for the current set?" in message


def test_is_acceptable_live_toolhouse_outcome_accepts_safe_hosted_statuses() -> None:
    for status in ["answered", "needs_more_evidence", "external_context_only", "validation_risk"]:
        assert is_acceptable_live_toolhouse_outcome(
            {
                "status": status,
                "toolhouse_fallback": False,
                "dependency_state": {"toolhouse": True},
                "validation": {"valid": True},
            }
        )


def test_is_acceptable_live_toolhouse_outcome_rejects_fallback_and_invalid_states() -> None:
    assert not is_acceptable_live_toolhouse_outcome(
        {
            "status": "answered",
            "toolhouse_fallback": True,
            "dependency_state": {"toolhouse": False},
            "validation": {"valid": True},
        }
    )
    assert not is_acceptable_live_toolhouse_outcome(
        {
            "status": "mcp_unavailable",
            "toolhouse_fallback": False,
            "dependency_state": {"toolhouse": True},
            "validation": {"valid": True},
        }
    )