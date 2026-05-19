from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.answering.query_service import explain_query
from app.config import get_settings
from app.db.session import SessionFactory
from app.models import IngestionJob, SlackEvent
from app.slack.gateway import SlackGateway


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _payload_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _strip_bot_mention(text: str) -> str:
    return re.sub(r"^<@[^>]+>\s*", "", text).strip()


def _event_retry_meta(headers: dict[str, str]) -> tuple[int | None, str | None]:
    retry_num_raw = headers.get("x-slack-retry-num")
    retry_reason = headers.get("x-slack-retry-reason")
    retry_num = int(retry_num_raw) if retry_num_raw is not None else None
    return retry_num, retry_reason


def _merge_checkpoint_json(existing: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    merged.update(updates)
    return merged


def _normalize_slack_mrkdwn(text: str) -> str:
    normalized = text.replace("\r\n", "\n").strip()
    normalized = re.sub(r"\*\*(.+?)\*\*", r"*\1*", normalized)
    normalized = re.sub(r"(^|\n)[•·]\s+", r"\1- ", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized


def _short_reason_for_payload(payload: dict[str, Any]) -> str:
    if payload.get("answer_mode") == "agent_mode":
        toolhouse_response = payload.get("toolhouse_response") or {}
        reasoning_summary = str(toolhouse_response.get("reasoning_summary") or "").strip()
        if reasoning_summary:
            return reasoning_summary.rstrip(".")
        escalation_payload = payload.get("escalation_payload") or {}
        decision_summary = escalation_payload.get("decision_summary") or {}
        selection_reason = str(decision_summary.get("selection_reason") or "").strip()
        if selection_reason:
            return selection_reason.rstrip(".")
        dependency_state = dict(payload.get("dependency_state") or {})
        if payload.get("toolhouse_fallback"):
            return "local fallback over the current evidence bundle"
        if dependency_state.get("toolhouse"):
            return "Toolhouse synthesis over the current evidence bundle"
        return "deeper review over the current evidence bundle"

    if payload.get("data_quality_report"):
        return "indexed coverage and missing-field audit"
    if payload.get("status") == "no_results":
        return "relaxed filters to explain the miss"

    reason_codes = {str(code) for code in payload.get("reason_codes", [])}
    if "local_synthesis" in reason_codes:
        return "local tenant-fit heuristic over visible evidence"
    if "chunk_keyword_search" in reason_codes:
        return "keyword chunk matches over visible evidence"
    if "change_detection" in reason_codes or "conflict_review" in reason_codes:
        return "freshest correction outranked older conflicting evidence"
    if "aggregation" in reason_codes:
        return "structured aggregation over normalized property records"
    if "source_lookup" in reason_codes:
        return "field lookup over stored source evidence"
    if "proximity" in reason_codes:
        return "backend distance ranking over visible evidence"
    return "structured filters over normalized property records"


def _route_label_for_payload(payload: dict[str, Any]) -> str:
    if payload.get("answer_mode") == "agent_mode":
        status = str(payload.get("status") or "answered")
        if status == "validation_risk":
            return "Validation risk"
        if status == "needs_more_evidence":
            return "Needs evidence"
        if status == "mcp_unavailable":
            return "MCP unavailable"
        return "Deeper review"

    if payload.get("data_quality_report"):
        return "Data quality"
    if payload.get("status") == "no_results":
        return "No direct match"

    reason_codes = {str(code) for code in payload.get("reason_codes", [])}
    route_mode = str(payload.get("route_mode") or "instant")
    if "proximity" in reason_codes:
        return "Proximity search"
    if "local_synthesis" in reason_codes:
        return "Expanded search"
    if "chunk_keyword_search" in reason_codes:
        return "Keyword match"
    if "change_detection" in reason_codes or "conflict_review" in reason_codes:
        return "Conflict review"
    if route_mode == "failed":
        return "Unsupported"
    return "Direct match"


def _boundary_label_for_payload(payload: dict[str, Any]) -> str:
    if payload.get("answer_mode") == "agent_mode":
        validation = dict(payload.get("validation") or {})
        dependency_state = dict(payload.get("dependency_state") or {})
        if payload.get("toolhouse_fallback"):
            return "local fallback, citations validated"
        if dependency_state.get("local_deeper_review"):
            return "local deeper review, citations validated"
        if dependency_state.get("toolhouse") and validation.get("valid"):
            return "Toolhouse-backed, citations validated"
        if dependency_state.get("toolhouse"):
            return "Toolhouse-backed, bounded to allowed evidence"
        return "bounded to current evidence bundle"

    route_mode = str(payload.get("route_mode") or "instant")
    if route_mode == "hybrid":
        return "local heuristic over visible evidence"
    return "backend-grounded"


def build_trust_receipt_text(payload: dict[str, Any]) -> str:
    if payload.get("answer_mode") == "agent_mode":
        evidence_count = len(list(((payload.get("escalation_payload") or {}).get("evidence") or [])))
        if evidence_count == 0:
            evidence_count = int(((payload.get("validation") or {}).get("allowed_evidence_count") or 0))
        mode_label = "Agent mode"
    else:
        evidence_count = int(payload.get("evidence_count") or 0)
        mode_label = "Instant answer"
    source_label = f"{evidence_count} source{'s' if evidence_count != 1 else ''}"
    return " • ".join(
        [
            mode_label,
            _route_label_for_payload(payload),
            source_label,
            _short_reason_for_payload(payload),
            _boundary_label_for_payload(payload),
        ]
    )


def _comparison_table_from_evidence(payload: dict[str, Any]) -> dict[str, object] | None:
    escalation_payload = payload.get("escalation_payload") or {}
    evidence = list(escalation_payload.get("evidence") or [])
    rows: list[list[str]] = []
    for item in evidence[:5]:
        property_record = dict(item.get("property_record") or {})
        if not property_record:
            continue
        rows.append(
            [
                str(property_record.get("address") or "-"),
                f"{int(property_record['sq_ft']):,} SF" if property_record.get("sq_ft") is not None else "unknown SF",
                f"${property_record['price_per_sq_ft']}/SF" if property_record.get("price_per_sq_ft") is not None else "unknown price",
                str(property_record.get("availability") or "-"),
            ]
        )
    if len(rows) < 2:
        return None
    return {"title": "Quick comparison", "columns": ["Addr", "SF", "Rent", "Avail"], "rows": rows}


def _normalize_comparison_table(payload: dict[str, Any]) -> dict[str, object] | None:
    table = payload.get("comparison_table")
    if not isinstance(table, dict):
        table = _comparison_table_from_evidence(payload)
    if not isinstance(table, dict):
        return None
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not columns or not isinstance(rows, list) or len(rows) < 2:
        return None
    normalized_columns = [str(value).strip() for value in columns if str(value).strip()]
    normalized_rows: list[list[str]] = []
    for row in rows[:5]:
        if not isinstance(row, list):
            continue
        values = [str(value).strip() for value in row[: len(normalized_columns)]]
        if len(values) != len(normalized_columns):
            continue
        normalized_rows.append(values)
    if len(normalized_rows) < 2:
        return None
    title = str(table.get("title") or "Quick comparison").strip()
    return {"title": title, "columns": normalized_columns, "rows": normalized_rows}


def _truncate_table_cell(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: max(1, width - 1)] + "…"


def _render_table_block_text(table: dict[str, object]) -> str:
    columns = [str(value) for value in table["columns"]]
    rows = [[str(value) for value in row] for row in table["rows"]]
    widths = [len(column) for column in columns]
    max_widths = [18, 10, 10, 12, 8]
    for row in rows:
        for index, value in enumerate(row):
            widths[index] = min(max(widths[index], len(value)), max_widths[index] if index < len(max_widths) else 16)

    def render_row(values: list[str]) -> str:
        padded = []
        for index, value in enumerate(values):
            text = _truncate_table_cell(value, widths[index])
            padded.append(text.ljust(widths[index]))
        return "  ".join(padded).rstrip()

    lines = [render_row(columns), render_row(["-" * width for width in widths])]
    lines.extend(render_row(row) for row in rows)
    return f"*{table['title']}*\n```\n" + "\n".join(lines) + "\n```"


def build_comparison_table_block(payload: dict[str, Any]) -> dict[str, Any] | None:
    table = _normalize_comparison_table(payload)
    if table is None:
        return None
    return {"type": "section", "text": {"type": "mrkdwn", "text": _render_table_block_text(table)}}


def build_trust_receipt_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": _normalize_slack_mrkdwn(build_trust_receipt_text(payload)),
            }
        ],
    }


def _build_primary_answer_block(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": _normalize_slack_mrkdwn(str(payload.get("rendered_answer") or ""))},
    }


async def enqueue_app_mention_event(payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    settings = get_settings()
    event = dict(payload.get("event", {}))
    team_id = str(payload.get("team_id") or "")
    event_id = str(payload.get("event_id") or "")
    channel_id = str(event.get("channel") or "")
    retry_num, retry_reason = _event_retry_meta(headers)

    async with SessionFactory() as session:
        async with session.begin():
            existing_event = await session.scalar(
                select(SlackEvent).where(
                    SlackEvent.slack_team_id == team_id,
                    SlackEvent.slack_event_id == event_id,
                )
            )
            if existing_event is not None:
                if retry_num is not None:
                    existing_event.retry_num = retry_num
                if retry_reason is not None:
                    existing_event.retry_reason = retry_reason
                existing_event.processed_at = _utcnow()
                return {"status": "duplicate", "event_id": event_id}

            slack_event = SlackEvent(
                slack_event_id=event_id,
                slack_team_id=team_id or None,
                slack_channel_id=channel_id or None,
                event_type=str(event.get("type") or "unknown"),
                retry_num=retry_num,
                retry_reason=retry_reason,
                payload_hash=_payload_hash(payload),
                status="received",
            )
            session.add(slack_event)
            await session.flush()

            if channel_id not in settings.configured_channels:
                slack_event.status = "ignored"
                slack_event.error_code = "channel_not_allowed"
                slack_event.processed_at = _utcnow()
                return {"status": "ignored", "event_id": event_id, "channel_id": channel_id}

            query_text = _strip_bot_mention(str(event.get("text") or ""))
            thread_ts = str(event.get("thread_ts") or event.get("ts") or "")
            job = IngestionJob(
                job_type="answer_query",
                status="queued",
                attempt_count=0,
                checkpoint_json={
                    "slack_event_id": event_id,
                    "team_id": team_id,
                    "channel_id": channel_id,
                    "user_id": str(event.get("user") or ""),
                    "thread_ts": thread_ts,
                    "query_ts": str(event.get("ts") or ""),
                    "query_text": query_text,
                    "event_type": str(event.get("type") or ""),
                },
            )
            session.add(job)
            await session.flush()

            slack_event.status = "queued"
            slack_event.processed_at = _utcnow()
            return {
                "status": "queued",
                "event_id": event_id,
                "job_id": str(job.id),
                "channel_id": channel_id,
            }


def build_slack_reply_text(payload: dict[str, Any]) -> str:
    rendered_answer = _normalize_slack_mrkdwn(str(payload.get("rendered_answer") or ""))
    answer_mode = str(payload.get("answer_mode") or "instant_answer")
    if answer_mode == "agent_mode":
        dependency_state = dict(payload.get("dependency_state") or {})
        if payload.get("toolhouse_fallback"):
            detail = "local fallback deeper review"
        elif dependency_state.get("toolhouse"):
            detail = "Toolhouse-backed deeper review"
        elif dependency_state.get("local_deeper_review"):
            detail = "local deeper review"
        else:
            detail = "async deeper review"
        mode_label = f"_Mode: Agent mode - {detail}_"
    else:
        route_mode = str(payload.get("route_mode") or "instant")
        if route_mode == "hybrid":
            detail = "hybrid backend synthesis"
        elif route_mode == "failed":
            detail = "unsupported instant slice"
        else:
            detail = "structured backend retrieval"
        mode_label = f"_Mode: Instant answer - {detail}_"

    return mode_label if not rendered_answer else f"{mode_label}\n\n{rendered_answer}"


def build_answer_blocks(answer_payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = [_build_primary_answer_block(answer_payload)]
    table_block = build_comparison_table_block(answer_payload)
    if table_block is not None:
        blocks.append(table_block)
    blocks.append(build_trust_receipt_block(answer_payload))

    action_elements: list[dict[str, Any]] = []
    query_id = answer_payload.get("query_id")
    evidence_count = int(answer_payload.get("evidence_count", 0))
    if query_id and evidence_count > 0:
        action_elements.append(
            {
                "type": "button",
                "action_id": "show_sources",
                "text": {"type": "plain_text", "text": "Show sources"},
                "value": str(query_id),
            }
        )
    if query_id and (evidence_count > 0 or answer_payload.get("status") in {"unsupported", "no_results"}):
        action_elements.append(
            {
                "type": "button",
                "action_id": "look_deeper",
                "text": {"type": "plain_text", "text": "Look deeper"},
                "value": str(query_id),
            }
        )
    if action_elements:
        blocks.append(
            {
                "type": "actions",
                "elements": action_elements,
            }
        )
    return blocks


def build_deeper_review_blocks(deeper_payload: dict[str, Any]) -> list[dict[str, Any]]:
    blocks = [_build_primary_answer_block(deeper_payload)]
    table_block = build_comparison_table_block(deeper_payload)
    if table_block is not None:
        blocks.append(table_block)
    blocks.append(build_trust_receipt_block(deeper_payload))
    allowed_ids = list(((deeper_payload.get("escalation_payload") or {}).get("allowed_evidence_ids") or []))
    cited_ids = list(deeper_payload.get("cited_evidence_ids") or [])
    if deeper_payload.get("query_id") and (allowed_ids or cited_ids):
        blocks.append(
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "action_id": "show_sources",
                        "text": {"type": "plain_text", "text": "Show sources"},
                        "value": str(deeper_payload["query_id"]),
                    }
                ],
            }
        )
    return blocks


def build_pending_status_text(*, job_type: str) -> str:
    if job_type == "look_deeper":
        return "_Mode: Agent mode - checking backend context_\n\n_Review in progress inside this thread._"
    return "_Mode: Instant answer - searching visible evidence_\n\n_Gathering the best visible evidence for this thread._"


def build_pending_status_blocks(*, job_type: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": build_pending_status_text(job_type=job_type)},
        }
    ]


def build_failed_status_text(*, job_type: str) -> str:
    if job_type == "look_deeper":
        return "_Mode: Agent mode - review failed_\n\nI could not finish the deeper review cleanly. Please retry *Look deeper*."
    return "_Mode: Instant answer - processing failed_\n\nI could not finish the instant answer cleanly. Please retry the question."


def build_failed_status_blocks(*, job_type: str) -> list[dict[str, Any]]:
    return [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": build_failed_status_text(job_type=job_type)},
        }
    ]


def build_show_sources_text(explain_payload: dict[str, Any]) -> str:
    if explain_payload.get("status") != "explained":
        return str(explain_payload.get("message") or "No stored sources are available for that answer.")

    lines = [f"*Sources for:* {explain_payload['query_text']}"]
    evidence_items = list(explain_payload.get("evidence", []))
    if not evidence_items and explain_payload.get("data_quality_report"):
        report = dict(explain_payload.get("data_quality_report") or {})
        lines.append(f"- Sources indexed: {report.get('source_document_count')}")
        lines.append(f"- Property records indexed: {report.get('property_record_count')}")
        sources_without_properties = list(report.get("sources_without_properties", []))
        if sources_without_properties:
            lines.append(f"- Sources without property rows: {', '.join(map(str, sources_without_properties[:4]))}")
        return "\n".join(lines)

    grouped: dict[str, list[dict[str, Any]]] = {}
    for evidence in evidence_items:
        role = str(evidence.get("evidence_role") or "supporting")
        grouped.setdefault(role, []).append(evidence)

    role_order = ["selected", "result", "candidate", "supporting", "superseded"]
    for role in [*role_order, *sorted(set(grouped) - set(role_order))]:
        role_items = grouped.get(role, [])
        if not role_items:
            continue
        lines.append("")
        lines.append(f"*{role.replace('_', ' ').title()}*")
        for evidence in role_items:
            summary = str(evidence.get("source_summary") or "Unknown source")
            source_document = dict(evidence.get("source_document") or {})
            source_url = source_document.get("source_url")
            if source_url:
                lines.append(f"- {summary} - {source_url}")
            else:
                lines.append(f"- {summary}")
    return "\n".join(lines)


async def handle_show_sources_action(
    *,
    query_id: str,
    channel_id: str,
    user_id: str,
    thread_ts: str,
    slack_gateway: SlackGateway,
) -> dict[str, Any]:
    explain_payload = await explain_query(query_id)
    text = build_show_sources_text(explain_payload)
    await slack_gateway.post_ephemeral(channel_id=channel_id, user_id=user_id, thread_ts=thread_ts or None, text=text)
    return explain_payload


async def handle_look_deeper_action(
    *,
    query_id: str,
    channel_id: str,
    user_id: str,
    thread_ts: str,
    slack_gateway: SlackGateway,
) -> dict[str, Any]:
    async with SessionFactory() as session:
        async with session.begin():
            job = IngestionJob(
                job_type="look_deeper",
                status="queued",
                attempt_count=0,
                checkpoint_json={
                    "query_id": query_id,
                    "channel_id": channel_id,
                    "user_id": user_id,
                    "thread_ts": thread_ts,
                    "requested_at": _utcnow().isoformat(),
                },
            )
            session.add(job)
            await session.flush()
            job_id = str(job.id)

    await slack_gateway.post_ephemeral(
        channel_id=channel_id,
        user_id=user_id,
        thread_ts=thread_ts or None,
        text="On it. Entering agent mode and checking the messy bits.",
    )
    return {"status": "queued", "job_id": job_id, "query_id": query_id}


__all__ = [
    "build_deeper_review_blocks",
    "build_answer_blocks",
    "build_failed_status_blocks",
    "build_failed_status_text",
    "build_pending_status_blocks",
    "build_pending_status_text",
    "build_slack_reply_text",
    "build_show_sources_text",
    "enqueue_app_mention_event",
    "handle_look_deeper_action",
    "handle_show_sources_action",
]