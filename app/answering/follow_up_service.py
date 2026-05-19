from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.answering.query_service import answer_query
from app.answering.follow_up_suggestions import resolve_suggested_follow_up
from app.answering.thread_sessions import (
    assess_evidence_coverage,
    create_thread_query_from_evidence,
    load_thread_session_payload,
    record_query_in_thread_session,
    render_thread_evidence_answer,
)
from app.toolhouse import run_toolhouse_deeper_review


FOLLOW_UP_MODES = {"instant", "auto", "agent"}


def _normalized_mode(mode: str | None) -> str:
    value = str(mode or "auto").strip().lower()
    return value if value in FOLLOW_UP_MODES else "auto"


def _thread_session_filters(
    *,
    parent_query_id: str | None,
    mode: str,
    resolution: str,
    coverage: dict[str, object] | None,
    session_payload: dict[str, object],
) -> dict[str, object]:
    accumulated_evidence_ids = list(session_payload.get("accumulated_evidence_ids") or [])
    query_history = list(session_payload.get("query_history") or [])
    missing_signals = list((coverage or {}).get("missing_signals") or [])
    recommended_mcp_calls = list((coverage or {}).get("recommended_mcp_calls") or [])
    return {
        "follow_up": {
            "parent_query_id": parent_query_id,
            "requested_mode": mode,
            "resolution": resolution,
            "coverage": coverage,
        },
        "thread_session": {
            "thread_session_id": session_payload.get("thread_session_id"),
            "slack_channel_id": session_payload.get("slack_channel_id"),
            "slack_thread_ts": session_payload.get("slack_thread_ts"),
            "prior_accumulated_evidence_ids": accumulated_evidence_ids,
            "query_history": query_history[-10:],
            "missing_signals": missing_signals,
            "recommended_mcp_calls": recommended_mcp_calls,
        },
    }


async def _resolve_agent_follow_up(
    *,
    query_text: str,
    parent_query_id: str | None,
    mode: str,
    resolution: str,
    coverage: dict[str, object] | None,
    session_payload: dict[str, object],
    slack_channel_id: str | None,
    slack_user_id: str | None,
    slack_ts: str | None,
    slack_thread_ts: str | None,
) -> dict[str, object]:
    evidence_ids = [str(value) for value in list(session_payload.get("accumulated_evidence_ids") or [])]
    seed_payload = await create_thread_query_from_evidence(
        query_text=query_text,
        evidence_ids=evidence_ids,
        rendered_answer=(
            "*Follow-up agent request*\n"
            "Using the accumulated thread evidence bundle and backend MCP checks before answering."
        ),
        route_mode="agent_follow_up",
        route_confidence=Decimal("1.0000"),
        reason_codes=["follow_up", "follow_up_agent", resolution],
        slack_channel_id=slack_channel_id,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        slack_thread_ts=slack_thread_ts,
        filters=_thread_session_filters(
            parent_query_id=parent_query_id,
            mode=mode,
            resolution=resolution,
            coverage=coverage,
            session_payload=session_payload,
        ),
        dependency_state={"follow_up": True, "thread_session": True, "toolhouse_direct": True},
        model_versions={"answering": "follow-up-agent-v1"},
    )
    deeper_payload = await run_toolhouse_deeper_review(str(seed_payload["query_id"]))
    await record_query_in_thread_session(
        str(seed_payload["query_id"]),
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        role="follow_up",
        mode=mode,
        coverage=coverage,
    )
    deeper_payload["follow_up"] = {"mode": mode, "resolution": resolution, "coverage": coverage}
    return deeper_payload


async def resolve_follow_up_request(
    *,
    query_text: str,
    mode: str | None,
    parent_query_id: str | None,
    slack_channel_id: str,
    slack_user_id: str | None,
    slack_ts: str | None,
    slack_thread_ts: str,
    suggested_follow_up: dict[str, object] | None = None,
) -> dict[str, object]:
    selected_mode = _normalized_mode(mode)
    if parent_query_id:
        await record_query_in_thread_session(
            parent_query_id,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            role="parent",
            mode="seed",
        )

    session_payload = await load_thread_session_payload(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        create=True,
    )

    if suggested_follow_up and suggested_follow_up.get("id"):
        return await resolve_suggested_follow_up(
            suggestion=suggested_follow_up,
            parent_query_id=parent_query_id,
            slack_channel_id=slack_channel_id,
            slack_user_id=slack_user_id,
            slack_ts=slack_ts,
            slack_thread_ts=slack_thread_ts,
        )

    if selected_mode == "instant":
        answer_payload = await answer_query(
            query_text,
            slack_channel_id=slack_channel_id,
            slack_user_id=slack_user_id,
            slack_ts=slack_ts,
            slack_thread_ts=slack_thread_ts,
        )
        await record_query_in_thread_session(
            str(answer_payload["query_id"]),
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            role="follow_up",
            mode="instant",
        )
        answer_payload["follow_up"] = {"mode": "instant", "resolution": "instant_override", "coverage": None}
        return answer_payload

    if selected_mode == "agent":
        return await _resolve_agent_follow_up(
            query_text=query_text,
            parent_query_id=parent_query_id,
            mode="agent",
            resolution="agent_override",
            coverage=None,
            session_payload=session_payload,
            slack_channel_id=slack_channel_id,
            slack_user_id=slack_user_id,
            slack_ts=slack_ts,
            slack_thread_ts=slack_thread_ts,
        )

    coverage = await assess_evidence_coverage(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        query_text=query_text,
    )
    session_payload = await load_thread_session_payload(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        create=True,
    )
    evidence_ids = [str(value) for value in list(session_payload.get("accumulated_evidence_ids") or [])]

    if coverage.get("is_sufficient"):
        rendered_answer = await render_thread_evidence_answer(
            query_text=query_text,
            evidence_ids=evidence_ids,
            coverage=coverage,
        )
        answer_payload = await create_thread_query_from_evidence(
            query_text=query_text,
            evidence_ids=evidence_ids,
            rendered_answer=rendered_answer,
            route_mode="instant",
            route_confidence=Decimal(str(coverage.get("confidence") or "0.9000")),
            reason_codes=["follow_up", "thread_evidence_reuse", "coverage_sufficient"],
            slack_channel_id=slack_channel_id,
            slack_user_id=slack_user_id,
            slack_ts=slack_ts,
            slack_thread_ts=slack_thread_ts,
            filters=_thread_session_filters(
                parent_query_id=parent_query_id,
                mode="auto",
                resolution="sufficient",
                coverage=coverage,
                session_payload=session_payload,
            ),
            dependency_state={"follow_up": True, "thread_session": True, "coverage_reuse": True},
            model_versions={"answering": "follow-up-instant-v1"},
        )
        await record_query_in_thread_session(
            str(answer_payload["query_id"]),
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            role="follow_up",
            mode="auto",
            coverage=coverage,
        )
        answer_payload["follow_up"] = {"mode": "auto", "resolution": "sufficient", "coverage": coverage}
        return answer_payload

    if coverage.get("needs_expansion"):
        answer_payload = await answer_query(
            query_text,
            slack_channel_id=slack_channel_id,
            slack_user_id=slack_user_id,
            slack_ts=slack_ts,
            slack_thread_ts=slack_thread_ts,
        )
        if int(answer_payload.get("evidence_count") or 0) > 0:
            await record_query_in_thread_session(
                str(answer_payload["query_id"]),
                slack_channel_id=slack_channel_id,
                slack_thread_ts=slack_thread_ts,
                role="follow_up",
                mode="auto",
                coverage=coverage,
                evidence_limit=2,
            )
            answer_payload["follow_up"] = {"mode": "auto", "resolution": "needs_expansion", "coverage": coverage}
            return answer_payload

    return await _resolve_agent_follow_up(
        query_text=query_text,
        parent_query_id=parent_query_id,
        mode="auto",
        resolution="new_bundle_needed",
        coverage=coverage,
        session_payload=session_payload,
        slack_channel_id=slack_channel_id,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        slack_thread_ts=slack_thread_ts,
    )


__all__ = ["FOLLOW_UP_MODES", "resolve_follow_up_request"]