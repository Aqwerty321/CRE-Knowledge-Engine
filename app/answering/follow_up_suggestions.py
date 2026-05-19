from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.answering.thread_sessions import create_thread_query_from_evidence, load_thread_session_payload, record_query_in_thread_session
from app.config import get_settings
from app.db.session import SessionFactory
from app.models import EvidenceItem, PropertyRecord, SourceDocument, ThreadSession
from app.toolhouse.client import ToolhouseClient, parse_toolhouse_response_payload


SUGGESTION_LIMIT = 5
SUGGESTION_KINDS = ("average_rent", "availability_before_q3", "conflict_review", "largest_options", "price_spread")
_SUGGESTION_SOURCE_PRIORITY = {
    "toolhouse_answer": 40,
    "toolhouse_refresh": 30,
    "toolhouse": 25,
    "local_prevalidated": 10,
}

_SUGGESTION_TEMPLATES: dict[str, dict[str, str]] = {
    "average_rent": {
        "question": "What's the average rent for these?",
        "sql_query": (
            "SELECT AVG(pr.price_per_sq_ft) AS average_price_per_sq_ft, COUNT(*) AS priced_record_count "
            "FROM evidence_items ei JOIN property_records pr ON pr.id = ei.property_record_id "
            "WHERE ei.id = ANY(:evidence_ids) AND pr.price_per_sq_ft IS NOT NULL"
        ),
    },
    "availability_before_q3": {
        "question": "Which have availability before Q3 2026?",
        "sql_query": (
            "SELECT pr.address, pr.availability, pr.availability_date "
            "FROM evidence_items ei JOIN property_records pr ON pr.id = ei.property_record_id "
            "WHERE ei.id = ANY(:evidence_ids) AND pr.availability_date < DATE '2026-07-01' "
            "ORDER BY pr.availability_date NULLS LAST, pr.address"
        ),
    },
    "conflict_review": {
        "question": "Show me conflicts in this set",
        "sql_query": (
            "SELECT pr.duplicate_group_key, COUNT(*) AS record_count, COUNT(DISTINCT pr.sq_ft) AS sq_ft_versions, "
            "COUNT(DISTINCT pr.price_per_sq_ft) AS rent_versions, COUNT(DISTINCT pr.availability) AS availability_versions "
            "FROM evidence_items ei JOIN property_records pr ON pr.id = ei.property_record_id "
            "WHERE ei.id = ANY(:evidence_ids) AND pr.duplicate_group_key IS NOT NULL "
            "GROUP BY pr.duplicate_group_key HAVING COUNT(*) > 1"
        ),
    },
    "largest_options": {
        "question": "Which are the largest options?",
        "sql_query": (
            "SELECT pr.address, pr.sq_ft, pr.price_per_sq_ft, pr.availability "
            "FROM evidence_items ei JOIN property_records pr ON pr.id = ei.property_record_id "
            "WHERE ei.id = ANY(:evidence_ids) AND pr.sq_ft IS NOT NULL "
            "ORDER BY pr.sq_ft DESC LIMIT 5"
        ),
    },
    "price_spread": {
        "question": "What's the rent spread in this set?",
        "sql_query": (
            "SELECT pr.address, pr.price_per_sq_ft, pr.sq_ft, pr.availability "
            "FROM evidence_items ei JOIN property_records pr ON pr.id = ei.property_record_id "
            "WHERE ei.id = ANY(:evidence_ids) AND pr.price_per_sq_ft IS NOT NULL "
            "ORDER BY pr.price_per_sq_ft ASC"
        ),
    },
}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid_strings(values: list[object] | tuple[object, ...]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            normalized = str(UUID(str(value)))
        except (TypeError, ValueError):
            continue
        if normalized not in seen:
            result.append(normalized)
            seen.add(normalized)
    return result


def _evidence_fingerprint(evidence_ids: list[str]) -> str:
    return hashlib.sha1("|".join(sorted(_uuid_strings(evidence_ids))).encode("utf-8")).hexdigest()[:12]


def _suggestion_id(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    parent_query_id: str | None,
    kind: str,
    evidence_fingerprint: str,
    source_query_id: str | None = None,
) -> str:
    raw_value = "|".join([slack_channel_id, slack_thread_ts, parent_query_id or "", source_query_id or "", kind, evidence_fingerprint])
    return hashlib.sha1(raw_value.encode("utf-8")).hexdigest()[:16]


def _safe_question(value: object, fallback: str) -> str:
    normalized = " ".join(str(value or "").split())
    if not normalized:
        return fallback
    return normalized[:74]


def _infer_kind_from_question(question: str) -> str | None:
    normalized = " ".join(question.lower().replace("?", " ").split())
    if "average" in normalized and ("rent" in normalized or "price" in normalized):
        return "average_rent"
    if "before q3" in normalized or "q3 2026" in normalized or "available before" in normalized:
        return "availability_before_q3"
    if "conflict" in normalized or "disagree" in normalized or "mismatch" in normalized:
        return "conflict_review"
    if "largest" in normalized or "biggest" in normalized or "most sf" in normalized:
        return "largest_options"
    if "spread" in normalized or "range" in normalized or "cheapest" in normalized or "priciest" in normalized:
        return "price_spread"
    return None


def _candidate_questions(values: object) -> list[dict[str, object]]:
    if not isinstance(values, list):
        return []
    candidates: list[dict[str, object]] = []
    for value in values:
        if isinstance(value, dict):
            kind = str(value.get("kind") or "").strip()
            question = _safe_question(value.get("question"), _SUGGESTION_TEMPLATES.get(kind, {}).get("question", ""))
        else:
            question = _safe_question(value, "")
            kind = _infer_kind_from_question(question) or ""
        if kind in SUGGESTION_KINDS and question:
            candidates.append({"kind": kind, "question": question})
    return candidates


def _toolhouse_suggestion_message(context: dict[str, object]) -> str:
    payload = {
        "task": "suggest_followups",
        "context": context,
        "allowed_kinds": list(SUGGESTION_KINDS),
        "instructions": (
            "Generate 3 to 5 concise CRE follow-up questions for a Slack modal. Return only JSON with "
            "suggested_followups: [{kind, question}]. kind must be one of allowed_kinds. Do not include SQL; "
            "the backend attaches prevalidated SQL templates and will ignore unsupported kinds. Prefer questions "
            "that can be answered from the current evidence bundle in instant mode."
        ),
    }
    return json.dumps(payload, indent=2, sort_keys=True)


async def _toolhouse_candidate_questions(context: dict[str, object]) -> list[dict[str, object]]:
    settings = get_settings()
    if not settings.toolhouse_api_key or not settings.toolhouse_agent_id:
        return []
    client = ToolhouseClient(api_key=settings.toolhouse_api_key, agent_id=settings.toolhouse_agent_id)
    try:
        result = await client.send_message(_toolhouse_suggestion_message(context))
    except Exception:
        return []
    payload = result.response_payload
    if payload is None:
        payload, _ = parse_toolhouse_response_payload(result.raw_response)
    suggestions = (payload or {}).get("suggested_followups")
    if not isinstance(suggestions, list):
        return []
    return [dict(item) for item in suggestions if isinstance(item, dict)]


def _build_prevalidated_suggestions(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    parent_query_id: str | None,
    evidence_ids: list[str],
    toolhouse_candidates: list[dict[str, object]],
    source: str,
    source_query_id: str | None = None,
    source_run_id: str | None = None,
    include_local_defaults: bool = True,
) -> list[dict[str, object]]:
    if not evidence_ids:
        return []

    questions_by_kind: dict[str, str] = {}
    for item in _candidate_questions(toolhouse_candidates):
        kind = str(item.get("kind") or "").strip()
        if kind in SUGGESTION_KINDS and kind not in questions_by_kind:
            questions_by_kind[kind] = _safe_question(item.get("question"), _SUGGESTION_TEMPLATES[kind]["question"])

    suggestions: list[dict[str, object]] = []
    kinds = list(SUGGESTION_KINDS if include_local_defaults or not questions_by_kind else questions_by_kind)
    fingerprint = _evidence_fingerprint(evidence_ids)
    generated_at = _utcnow().isoformat()
    for kind in kinds:
        template = _SUGGESTION_TEMPLATES[kind]
        suggestion_source = source if kind in questions_by_kind else "local_prevalidated"
        suggestions.append(
            {
                "id": _suggestion_id(
                    slack_channel_id=slack_channel_id,
                    slack_thread_ts=slack_thread_ts,
                    parent_query_id=parent_query_id,
                    kind=kind,
                    evidence_fingerprint=fingerprint,
                    source_query_id=source_query_id,
                ),
                "kind": kind,
                "question": questions_by_kind.get(kind, template["question"]),
                "mode": "instant",
                "route_mode": "instant",
                "sql_query": template["sql_query"],
                "sql_params": {"evidence_ids": evidence_ids},
                "status": "unanswered",
                "generated_at": generated_at,
                "generated_by_query_id": source_query_id,
                "toolhouse_run_id": source_run_id,
                "evidence_fingerprint": fingerprint,
                "validation": {
                    "status": "prevalidated",
                    "executor": "backend_instant_template",
                    "raw_sql_execution": False,
                },
                "source": suggestion_source,
                "priority": _SUGGESTION_SOURCE_PRIORITY.get(suggestion_source, 0),
            }
        )
    return suggestions[:SUGGESTION_LIMIT]


def _suggestion_evidence_ids(suggestion: dict[str, object]) -> list[str]:
    sql_params = suggestion.get("sql_params") if isinstance(suggestion.get("sql_params"), dict) else {}
    return _uuid_strings(list(sql_params.get("evidence_ids") or []))


def _rank_active_suggestions(
    suggestions: list[dict[str, object]],
    *,
    current_evidence_ids: list[str],
    limit: int = SUGGESTION_LIMIT,
) -> list[dict[str, object]]:
    current_set = set(_uuid_strings(current_evidence_ids))
    current_fingerprint = _evidence_fingerprint(list(current_set)) if current_set else ""
    candidates: list[dict[str, object]] = []
    for suggestion in suggestions:
        if str(suggestion.get("status") or "unanswered") == "answered":
            continue
        kind = str(suggestion.get("kind") or "")
        if kind not in SUGGESTION_KINDS:
            continue
        evidence_ids = set(_suggestion_evidence_ids(suggestion))
        if not evidence_ids:
            continue
        if current_set and not evidence_ids.issubset(current_set):
            continue
        candidates.append(dict(suggestion))

    def sort_key(suggestion: dict[str, object]) -> tuple[int, int, str, int]:
        kind = str(suggestion.get("kind") or "")
        source = str(suggestion.get("source") or "")
        return (
            1 if current_fingerprint and suggestion.get("evidence_fingerprint") == current_fingerprint else 0,
            int(suggestion.get("priority") or _SUGGESTION_SOURCE_PRIORITY.get(source, 0)),
            str(suggestion.get("generated_at") or ""),
            -SUGGESTION_KINDS.index(kind) if kind in SUGGESTION_KINDS else -100,
        )

    ranked = sorted(candidates, key=sort_key, reverse=True)
    selected: list[dict[str, object]] = []
    seen_kinds: set[str] = set()
    for suggestion in ranked:
        kind = str(suggestion.get("kind") or "")
        if kind in seen_kinds:
            continue
        selected.append(suggestion)
        seen_kinds.add(kind)
        if len(selected) >= limit:
            break
    return selected


async def _store_suggestions(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    parent_query_id: str | None,
    suggestions: list[dict[str, object]],
) -> None:
    await load_thread_session_payload(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts, create=True)
    async with SessionFactory() as session:
        async with session.begin():
            thread_session = await session.scalar(
                select(ThreadSession).where(
                    ThreadSession.slack_channel_id == slack_channel_id,
                    ThreadSession.slack_thread_ts == slack_thread_ts,
                )
            )
            if thread_session is None:
                return
            context = dict(thread_session.session_context_json or {})
            suggestion_payload = context.get("follow_up_suggestions") if isinstance(context.get("follow_up_suggestions"), dict) else {}
            existing = suggestion_payload.get("suggestions") if isinstance(suggestion_payload, dict) else []
            if not isinstance(existing, list):
                existing = []
            merged: dict[str, dict[str, object]] = {
                str(suggestion.get("id") or ""): dict(suggestion)
                for suggestion in existing
                if isinstance(suggestion, dict) and suggestion.get("id")
            }
            for suggestion in suggestions:
                if suggestion.get("id"):
                    merged[str(suggestion["id"])] = dict(suggestion)
            current_evidence_ids = _uuid_strings(list(thread_session.accumulated_evidence_ids_json or []))
            if not current_evidence_ids:
                for suggestion in suggestions:
                    current_evidence_ids.extend(_suggestion_evidence_ids(suggestion))
                current_evidence_ids = _uuid_strings(current_evidence_ids)
            active = _rank_active_suggestions(list(merged.values()), current_evidence_ids=current_evidence_ids)
            context["follow_up_suggestions"] = {
                "parent_query_id": parent_query_id,
                "updated_at": _utcnow().isoformat(),
                "active_ids": [str(suggestion.get("id") or "") for suggestion in active],
                "suggestions": list(merged.values()),
            }
            thread_session.session_context_json = context
            thread_session.updated_at = _utcnow()


async def generate_and_store_follow_up_suggestions(
    *,
    parent_query_id: str | None,
    slack_channel_id: str,
    slack_thread_ts: str,
    force_refresh: bool = False,
) -> list[dict[str, object]]:
    if not force_refresh:
        cached = await load_follow_up_suggestions(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts)
        if cached:
            return cached

    if parent_query_id:
        await record_query_in_thread_session(
            parent_query_id,
            slack_channel_id=slack_channel_id,
            slack_thread_ts=slack_thread_ts,
            role="parent",
            mode="suggestions_seed",
        )
    session_payload = await load_thread_session_payload(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        create=True,
    )
    evidence_ids = _uuid_strings(list(session_payload.get("accumulated_evidence_ids") or []))
    context = {
        "parent_query_id": parent_query_id,
        "slack_channel_id": slack_channel_id,
        "slack_thread_ts": slack_thread_ts,
        "evidence_count": len(evidence_ids),
        "query_history": list(session_payload.get("query_history") or [])[-5:],
    }
    candidates = await _toolhouse_candidate_questions(context)
    suggestions = _build_prevalidated_suggestions(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        parent_query_id=parent_query_id,
        evidence_ids=evidence_ids,
        toolhouse_candidates=candidates,
        source="toolhouse_refresh" if candidates else "local_prevalidated",
        source_query_id=parent_query_id,
        include_local_defaults=True,
    )
    await _store_suggestions(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        parent_query_id=parent_query_id,
        suggestions=suggestions,
    )
    return await load_follow_up_suggestions(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts)


async def store_agent_follow_up_suggestions(
    *,
    response_payload: dict[str, object],
    query_id: str,
    slack_channel_id: str,
    slack_thread_ts: str,
    parent_query_id: str | None,
    evidence_ids: list[str],
    toolhouse_run_id: str | None = None,
) -> list[dict[str, object]]:
    candidates = _candidate_questions(response_payload.get("next_followups") or response_payload.get("suggested_followups"))
    if not candidates:
        return await load_follow_up_suggestions(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts)
    suggestions = _build_prevalidated_suggestions(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        parent_query_id=parent_query_id,
        evidence_ids=_uuid_strings(evidence_ids),
        toolhouse_candidates=candidates,
        source="toolhouse_answer",
        source_query_id=query_id,
        source_run_id=toolhouse_run_id,
        include_local_defaults=False,
    )
    await _store_suggestions(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        parent_query_id=parent_query_id,
        suggestions=suggestions,
    )
    return await load_follow_up_suggestions(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts)


async def load_follow_up_suggestion(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    suggestion_id: str,
) -> dict[str, object] | None:
    suggestions = await load_follow_up_suggestions(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts)
    for suggestion in suggestions:
        if str(suggestion.get("id") or "") == suggestion_id:
            return dict(suggestion)
    return None


async def load_follow_up_suggestions(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
) -> list[dict[str, object]]:
    async with SessionFactory() as session:
        thread_session = await session.scalar(
            select(ThreadSession).where(
                ThreadSession.slack_channel_id == slack_channel_id,
                ThreadSession.slack_thread_ts == slack_thread_ts,
            )
        )
        if thread_session is None:
            return []
        context = dict(thread_session.session_context_json or {})
        suggestion_payload = context.get("follow_up_suggestions") if isinstance(context.get("follow_up_suggestions"), dict) else {}
        suggestions = suggestion_payload.get("suggestions") if isinstance(suggestion_payload, dict) else []
        if not isinstance(suggestions, list):
            return []
        current_evidence_ids = _uuid_strings(list(thread_session.accumulated_evidence_ids_json or []))
        return _rank_active_suggestions(
            [dict(suggestion) for suggestion in suggestions if isinstance(suggestion, dict)],
            current_evidence_ids=current_evidence_ids,
        )


async def load_follow_up_suggestion_context(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
) -> dict[str, object]:
    suggestions = await load_follow_up_suggestions(slack_channel_id=slack_channel_id, slack_thread_ts=slack_thread_ts)
    return {
        "allowed_kinds": list(SUGGESTION_KINDS),
        "display_limit": SUGGESTION_LIMIT,
        "unanswered_suggestions": [
            {
                "id": suggestion.get("id"),
                "kind": suggestion.get("kind"),
                "question": suggestion.get("question"),
                "source": suggestion.get("source"),
                "generated_by_query_id": suggestion.get("generated_by_query_id"),
                "generated_at": suggestion.get("generated_at"),
            }
            for suggestion in suggestions
        ],
    }


async def _load_suggestion_rows(
    evidence_ids: list[str],
) -> list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]]:
    parsed_ids = [UUID(value) for value in _uuid_strings(evidence_ids)]
    if not parsed_ids:
        return []
    async with SessionFactory() as session:
        result = await session.execute(
            select(EvidenceItem, SourceDocument, PropertyRecord)
            .outerjoin(SourceDocument, EvidenceItem.document_id == SourceDocument.id)
            .outerjoin(PropertyRecord, EvidenceItem.property_record_id == PropertyRecord.id)
            .where(EvidenceItem.id.in_(parsed_ids))
        )
        rows = list(result.all())
    order = {evidence_id: index for index, evidence_id in enumerate(parsed_ids)}
    rows.sort(key=lambda row: order.get(row[0].id, len(order)))
    return [(str(row[0].id), row[0], row[1], row[2]) for row in rows]


def _money(value: Decimal | None) -> str:
    return "unknown" if value is None else f"${value:.2f}/SF"


def _format_property_line(property_record: PropertyRecord) -> str:
    sq_ft = "unknown SF" if property_record.sq_ft is None else f"{property_record.sq_ft:,} SF"
    return f"*{property_record.address or 'Unknown address'}* - {sq_ft}, {_money(property_record.price_per_sq_ft)}, {property_record.availability or 'availability unknown'}"


def _render_average_rent(rows: list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]]) -> tuple[str, list[str]]:
    priced = [(evidence_id, record) for evidence_id, _, _, record in rows if record is not None and record.price_per_sq_ft is not None]
    if not priced:
        return "*Average rent*\nNo priced records are present in the current thread evidence bundle.", [row[0] for row in rows]
    total = sum((record.price_per_sq_ft for _, record in priced), Decimal("0"))
    average = total / Decimal(len(priced))
    return (
        "*Average rent*\n"
        f"- Average asking rent is *${average:.2f}/SF* across *{len(priced)}* sourced record(s).\n"
        "- Scope is the current thread evidence bundle.",
        [evidence_id for evidence_id, _ in priced],
    )


def _render_availability_before_q3(rows: list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]]) -> tuple[str, list[str]]:
    matches = [
        (evidence_id, record)
        for evidence_id, _, _, record in rows
        if record is not None and record.availability_date is not None and record.availability_date.isoformat() < "2026-07-01"
    ]
    if not matches:
        checked_ids = [evidence_id for evidence_id, _, _, record in rows if record is not None and record.availability or record is not None]
        return "*Availability before Q3 2026*\nNo current thread evidence shows availability before Q3 2026.", checked_ids
    lines = ["*Availability before Q3 2026*"]
    for _, record in matches[:5]:
        lines.append(f"- {_format_property_line(record)}")
    return "\n".join(lines), [evidence_id for evidence_id, _ in matches[:5]]


def _render_conflicts(rows: list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]]) -> tuple[str, list[str]]:
    groups: dict[str, list[tuple[str, PropertyRecord]]] = {}
    for evidence_id, _, _, record in rows:
        if record is None or not record.duplicate_group_key:
            continue
        groups.setdefault(record.duplicate_group_key, []).append((evidence_id, record))
    conflict_groups: list[tuple[str, list[tuple[str, PropertyRecord]]]] = []
    for key, records in groups.items():
        if len(records) < 2:
            continue
        sq_ft_values = {record.sq_ft for _, record in records if record.sq_ft is not None}
        rent_values = {record.price_per_sq_ft for _, record in records if record.price_per_sq_ft is not None}
        availability_values = {record.availability for _, record in records if record.availability}
        if len(sq_ft_values) > 1 or len(rent_values) > 1 or len(availability_values) > 1:
            conflict_groups.append((key, records))
    if not conflict_groups:
        return "*Conflict check*\nNo obvious square-footage, rent, or availability conflicts were found in this thread evidence bundle.", [row[0] for row in rows]
    lines = ["*Conflict check*"]
    cited_ids: list[str] = []
    for key, records in conflict_groups[:3]:
        lines.append(f"- *{key}* has {len(records)} sourced versions in the thread bundle.")
        cited_ids.extend(evidence_id for evidence_id, _ in records[:3])
    return "\n".join(lines), cited_ids


def _render_largest(rows: list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]]) -> tuple[str, list[str]]:
    sized = [(evidence_id, record) for evidence_id, _, _, record in rows if record is not None and record.sq_ft is not None]
    sized.sort(key=lambda item: item[1].sq_ft or 0, reverse=True)
    if not sized:
        return "*Largest options*\nNo square-footage values are present in the current thread evidence bundle.", [row[0] for row in rows]
    lines = ["*Largest options*"]
    for _, record in sized[:5]:
        lines.append(f"- {_format_property_line(record)}")
    return "\n".join(lines), [evidence_id for evidence_id, _ in sized[:5]]


def _render_price_spread(rows: list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]]) -> tuple[str, list[str]]:
    priced = [(evidence_id, record) for evidence_id, _, _, record in rows if record is not None and record.price_per_sq_ft is not None]
    priced.sort(key=lambda item: item[1].price_per_sq_ft or Decimal("0"))
    if len(priced) < 2:
        return "*Rent spread*\nNot enough priced records are present in the current thread evidence bundle.", [evidence_id for evidence_id, _ in priced]
    cheapest_id, cheapest = priced[0]
    priciest_id, priciest = priced[-1]
    return (
        "*Rent spread*\n"
        f"- Lowest asking rent: {_format_property_line(cheapest)}\n"
        f"- Highest asking rent: {_format_property_line(priciest)}",
        [cheapest_id, priciest_id],
    )


def _render_suggestion_answer(
    *,
    suggestion: dict[str, object],
    rows: list[tuple[str, EvidenceItem, SourceDocument | None, PropertyRecord | None]],
) -> tuple[str, list[str]]:
    kind = str(suggestion.get("kind") or "")
    if kind == "average_rent":
        return _render_average_rent(rows)
    if kind == "availability_before_q3":
        return _render_availability_before_q3(rows)
    if kind == "conflict_review":
        return _render_conflicts(rows)
    if kind == "largest_options":
        return _render_largest(rows)
    if kind == "price_spread":
        return _render_price_spread(rows)
    return "*Suggested follow-up*\nThat suggested follow-up is no longer available.", []


async def mark_follow_up_suggestion_answered(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    suggestion_id: str,
    answer_query_id: str,
) -> None:
    async with SessionFactory() as session:
        async with session.begin():
            thread_session = await session.scalar(
                select(ThreadSession).where(
                    ThreadSession.slack_channel_id == slack_channel_id,
                    ThreadSession.slack_thread_ts == slack_thread_ts,
                )
            )
            if thread_session is None:
                return
            context = dict(thread_session.session_context_json or {})
            suggestion_payload = context.get("follow_up_suggestions") if isinstance(context.get("follow_up_suggestions"), dict) else {}
            suggestions = suggestion_payload.get("suggestions") if isinstance(suggestion_payload, dict) else []
            if not isinstance(suggestions, list):
                return
            updated_suggestions: list[dict[str, object]] = []
            for suggestion in suggestions:
                if not isinstance(suggestion, dict):
                    continue
                updated_suggestion = dict(suggestion)
                if str(updated_suggestion.get("id") or "") == suggestion_id:
                    updated_suggestion["status"] = "answered"
                    updated_suggestion["answered_query_id"] = answer_query_id
                    updated_suggestion["answered_at"] = _utcnow().isoformat()
                updated_suggestions.append(updated_suggestion)
            active = _rank_active_suggestions(
                updated_suggestions,
                current_evidence_ids=_uuid_strings(list(thread_session.accumulated_evidence_ids_json or [])),
            )
            suggestion_payload = dict(suggestion_payload)
            suggestion_payload["active_ids"] = [str(suggestion.get("id") or "") for suggestion in active]
            suggestion_payload["suggestions"] = updated_suggestions
            suggestion_payload["updated_at"] = _utcnow().isoformat()
            context["follow_up_suggestions"] = suggestion_payload
            thread_session.session_context_json = context
            thread_session.updated_at = _utcnow()


async def resolve_suggested_follow_up(
    *,
    suggestion: dict[str, object],
    parent_query_id: str | None,
    slack_channel_id: str,
    slack_user_id: str | None,
    slack_ts: str | None,
    slack_thread_ts: str,
) -> dict[str, object]:
    evidence_ids = _uuid_strings(list((suggestion.get("sql_params") or {}).get("evidence_ids") or [])) if isinstance(suggestion.get("sql_params"), dict) else []
    rows = await _load_suggestion_rows(evidence_ids)
    rendered_answer, cited_evidence_ids = _render_suggestion_answer(suggestion=suggestion, rows=rows)
    if not cited_evidence_ids:
        cited_evidence_ids = evidence_ids
    answer_payload = await create_thread_query_from_evidence(
        query_text=str(suggestion.get("question") or "Suggested follow-up"),
        evidence_ids=cited_evidence_ids,
        rendered_answer=rendered_answer,
        route_mode="instant",
        route_confidence=Decimal("1.0000"),
        reason_codes=["follow_up", "suggested_follow_up", "prevalidated_sql", str(suggestion.get("kind") or "unknown")],
        slack_channel_id=slack_channel_id,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        slack_thread_ts=slack_thread_ts,
        filters={
            "follow_up": {
                "parent_query_id": parent_query_id,
                "requested_mode": "instant",
                "resolution": "suggested_prevalidated_sql",
            },
            "suggested_follow_up": suggestion,
        },
        dependency_state={"follow_up": True, "suggested_follow_up": True, "prevalidated_sql": True},
        model_versions={"answering": "follow-up-suggestion-v1"},
    )
    await record_query_in_thread_session(
        str(answer_payload["query_id"]),
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        role="follow_up",
        mode="instant_suggestion",
    )
    await mark_follow_up_suggestion_answered(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        suggestion_id=str(suggestion.get("id") or ""),
        answer_query_id=str(answer_payload["query_id"]),
    )
    answer_payload["follow_up"] = {"mode": "instant", "resolution": "suggested_prevalidated_sql", "suggestion": suggestion}
    return answer_payload


__all__ = [
    "generate_and_store_follow_up_suggestions",
    "load_follow_up_suggestion",
    "load_follow_up_suggestion_context",
    "load_follow_up_suggestions",
    "mark_follow_up_suggestion_answered",
    "resolve_suggested_follow_up",
    "store_agent_follow_up_suggestions",
]