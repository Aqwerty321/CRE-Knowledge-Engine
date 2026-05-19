from __future__ import annotations

from app.toolhouse.client import build_toolhouse_message, parse_toolhouse_response_payload


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