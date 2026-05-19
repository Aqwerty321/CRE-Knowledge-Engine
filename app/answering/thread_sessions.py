from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionFactory
from app.models import AnswerSnapshot, EvidenceItem, PropertyRecord, Query, SourceDocument, ThreadSession
from app.routing.query_constructor import build_structured_query_spec


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


def _uuid_values(values: list[object] | tuple[object, ...]) -> list[UUID]:
    return [UUID(value) for value in _uuid_strings(values)]


def _slack_context_payload(
    *,
    slack_channel_id: str | None,
    slack_user_id: str | None,
    slack_ts: str | None,
    slack_thread_ts: str | None,
) -> dict[str, object]:
    payload = {
        "channel_id": slack_channel_id,
        "user_id": slack_user_id,
        "message_ts": slack_ts,
        "thread_ts": slack_thread_ts or slack_ts,
    }
    return {key: value for key, value in payload.items() if value}


def _normalize_text(value: str) -> str:
    return " ".join(str(value or "").lower().replace("?", " ").replace(",", " ").split())


def extract_follow_up_signals(query_text: str) -> dict[str, object]:
    normalized = _normalize_text(query_text)
    required_fields: list[str] = []
    explicit_terms: list[str] = []

    def require(*fields: str) -> None:
        for field in fields:
            if field not in required_fields:
                required_fields.append(field)

    if any(term in normalized for term in ("where", "located", "location", "address", "market", "submarket")):
        require("address", "market")
    if any(term in normalized for term in ("best use", "use case", "fit", "tenant", "recommend", "best")):
        require("property_type", "sq_ft", "price_per_sq_ft", "availability")
    if any(term in normalized for term in ("price", "rent", "$/sf", "psf", "rate", "cheapest")):
        require("price_per_sq_ft")
    if any(term in normalized for term in ("size", "square", "sq ft", "sqft", "sf", "largest")):
        require("sq_ft")
    if any(term in normalized for term in ("available", "availability", "soon", "immediate", "timing")):
        require("availability")
    if any(term in normalized for term in ("source", "why", "where did", "came from")):
        require("source_summary")

    structured_spec = build_structured_query_spec(query_text)
    if structured_spec is not None:
        if structured_spec.address_terms:
            require("address")
            explicit_terms.extend(structured_spec.address_terms)
        if structured_spec.property_types:
            require("property_type")
            explicit_terms.extend(structured_spec.property_types)
        if structured_spec.markets:
            require("market")
            explicit_terms.extend(structured_spec.markets)
        if structured_spec.keywords:
            require("keyword_context")
            explicit_terms.extend(structured_spec.keywords)
        if structured_spec.price_per_sq_ft_lt is not None or structured_spec.price_per_sq_ft_gt is not None:
            require("price_per_sq_ft")
        if structured_spec.sq_ft_gte is not None or structured_spec.sq_ft_lte is not None:
            require("sq_ft")
        if structured_spec.availability_before is not None or structured_spec.require_immediate:
            require("availability")

    if not required_fields:
        require("general_context")

    return {
        "required_fields": required_fields,
        "explicit_terms": sorted(set(term for term in explicit_terms if term)),
        "normalized_query": normalized,
    }


async def _get_or_create_thread_session(
    session: AsyncSession,
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
) -> ThreadSession:
    record = await session.scalar(
        select(ThreadSession).where(
            ThreadSession.slack_channel_id == slack_channel_id,
            ThreadSession.slack_thread_ts == slack_thread_ts,
        )
    )
    if record is not None:
        return record

    record = ThreadSession(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        accumulated_evidence_ids_json=[],
        query_history_json=[],
        session_context_json={},
    )
    session.add(record)
    await session.flush()
    return record


def _query_history_entry(
    *,
    query_record: Query,
    snapshot: AnswerSnapshot | None,
    role: str,
    mode: str | None,
    coverage: dict[str, object] | None,
) -> dict[str, object]:
    evidence_ids = _uuid_strings(list(snapshot.evidence_ids or [])) if snapshot is not None else []
    entry: dict[str, object] = {
        "query_id": str(query_record.id),
        "query_text": query_record.query_text,
        "route_mode": query_record.route_mode,
        "route_confidence": str(query_record.route_confidence) if query_record.route_confidence is not None else None,
        "reason_codes": list(query_record.reason_codes or []),
        "evidence_ids": evidence_ids,
        "evidence_count": len(evidence_ids),
        "role": role,
        "created_at": query_record.created_at.isoformat() if query_record.created_at else None,
    }
    if mode:
        entry["mode"] = mode
    if coverage:
        entry["coverage"] = coverage
    return entry


async def record_query_in_thread_session(
    query_id: str,
    *,
    slack_channel_id: str | None = None,
    slack_thread_ts: str | None = None,
    role: str = "answer",
    mode: str | None = None,
    coverage: dict[str, object] | None = None,
    evidence_limit: int | None = None,
) -> dict[str, object]:
    try:
        parsed_query_id = UUID(str(query_id))
    except ValueError:
        return {"status": "invalid_query_id", "query_id": query_id}

    async with SessionFactory() as session:
        async with session.begin():
            query_record = await session.get(Query, parsed_query_id)
            if query_record is None:
                return {"status": "query_not_found", "query_id": query_id}

            snapshot = await session.scalar(select(AnswerSnapshot).where(AnswerSnapshot.query_id == query_record.id))
            filters = dict(snapshot.filters_json or {}) if snapshot is not None else {}
            slack_context = filters.get("slack_context") if isinstance(filters.get("slack_context"), dict) else {}
            channel_id = slack_channel_id or str(slack_context.get("channel_id") or query_record.slack_channel_id or "")
            thread_ts = slack_thread_ts or str(slack_context.get("thread_ts") or query_record.slack_ts or "")
            if not channel_id or not thread_ts:
                return {"status": "missing_thread_context", "query_id": query_id}

            thread_session = await _get_or_create_thread_session(
                session,
                slack_channel_id=channel_id,
                slack_thread_ts=thread_ts,
            )

            existing_ids = _uuid_strings(list(thread_session.accumulated_evidence_ids_json or []))
            new_ids = _uuid_strings(list(snapshot.evidence_ids or [])) if snapshot is not None else []
            if evidence_limit is not None:
                new_ids = new_ids[: max(0, evidence_limit)]
            merged_ids = [*existing_ids]
            seen = set(existing_ids)
            for evidence_id in new_ids:
                if evidence_id not in seen:
                    merged_ids.append(evidence_id)
                    seen.add(evidence_id)

            history = list(thread_session.query_history_json or [])
            history.append(
                _query_history_entry(
                    query_record=query_record,
                    snapshot=snapshot,
                    role=role,
                    mode=mode,
                    coverage=coverage,
                )
            )
            context = dict(thread_session.session_context_json or {})
            context.update(
                {
                    "last_query_id": str(query_record.id),
                    "last_query_text": query_record.query_text,
                    "last_role": role,
                    "last_mode": mode,
                    "last_coverage": coverage,
                    "updated_at": _utcnow().isoformat(),
                }
            )

            thread_session.accumulated_evidence_ids_json = merged_ids
            thread_session.query_history_json = history[-30:]
            thread_session.session_context_json = context
            thread_session.updated_at = _utcnow()
            return thread_session_payload(thread_session)


def thread_session_payload(thread_session: ThreadSession) -> dict[str, object]:
    return {
        "status": "ready",
        "thread_session_id": str(thread_session.id),
        "slack_channel_id": thread_session.slack_channel_id,
        "slack_thread_ts": thread_session.slack_thread_ts,
        "accumulated_evidence_ids": _uuid_strings(list(thread_session.accumulated_evidence_ids_json or [])),
        "query_history": list(thread_session.query_history_json or []),
        "session_context": dict(thread_session.session_context_json or {}),
        "created_at": thread_session.created_at.isoformat() if thread_session.created_at else None,
        "updated_at": thread_session.updated_at.isoformat() if thread_session.updated_at else None,
    }


async def load_thread_session_payload(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    create: bool = False,
) -> dict[str, object]:
    async with SessionFactory() as session:
        async with session.begin():
            if create:
                thread_session = await _get_or_create_thread_session(
                    session,
                    slack_channel_id=slack_channel_id,
                    slack_thread_ts=slack_thread_ts,
                )
            else:
                thread_session = await session.scalar(
                    select(ThreadSession).where(
                        ThreadSession.slack_channel_id == slack_channel_id,
                        ThreadSession.slack_thread_ts == slack_thread_ts,
                    )
                )
                if thread_session is None:
                    return {
                        "status": "not_found",
                        "slack_channel_id": slack_channel_id,
                        "slack_thread_ts": slack_thread_ts,
                        "accumulated_evidence_ids": [],
                        "query_history": [],
                        "session_context": {},
                    }
            return thread_session_payload(thread_session)


async def _load_evidence_rows(
    session: AsyncSession,
    evidence_ids: list[str],
) -> list[tuple[EvidenceItem, SourceDocument | None, PropertyRecord | None]]:
    parsed_ids = _uuid_values(evidence_ids)
    if not parsed_ids:
        return []
    result = await session.execute(
        select(EvidenceItem, SourceDocument, PropertyRecord)
        .outerjoin(SourceDocument, EvidenceItem.document_id == SourceDocument.id)
        .outerjoin(PropertyRecord, EvidenceItem.property_record_id == PropertyRecord.id)
        .where(EvidenceItem.id.in_(parsed_ids))
    )
    rows = list(result.all())
    order = {evidence_id: index for index, evidence_id in enumerate(parsed_ids)}
    rows.sort(key=lambda row: order.get(row[0].id, len(order)))
    return rows


def _coverage_fields_for_row(
    evidence_item: EvidenceItem,
    source_document: SourceDocument | None,
    property_record: PropertyRecord | None,
) -> set[str]:
    fields = set(evidence_item.matched_fields or [])
    if property_record is not None:
        if property_record.address:
            fields.add("address")
        if property_record.market:
            fields.add("market")
        if property_record.geo_lat is not None and property_record.geo_lng is not None:
            fields.add("geo")
        if property_record.property_type and property_record.property_type != "unknown":
            fields.add("property_type")
        if property_record.sq_ft is not None:
            fields.add("sq_ft")
        if property_record.price_per_sq_ft is not None:
            fields.add("price_per_sq_ft")
        if property_record.availability or property_record.availability_date:
            fields.add("availability")
    if source_document is not None or evidence_item.source_summary:
        fields.add("source_summary")
    if evidence_item.matched_fields or evidence_item.source_summary:
        fields.add("keyword_context")
        fields.add("general_context")
    return fields


def recommended_mcp_calls_for_missing(missing_signals: list[str], query_text: str) -> list[dict[str, object]]:
    calls: list[dict[str, object]] = []
    if any(signal in missing_signals for signal in ("address", "market", "geo", "property_type", "sq_ft", "price_per_sq_ft", "availability")):
        calls.append(
            {
                "tool": "search_properties",
                "why": "Find structured property rows that cover missing follow-up signals.",
                "arguments": {"filters": {"keywords": [query_text], "limit": 10}},
            }
        )
        calls.append(
            {
                "tool": "expand_query_evidence",
                "why": "Mint backend evidence IDs for any newly selected structured rows before citation.",
                "arguments": {"filters": {"keywords": [query_text], "limit": 5}},
            }
        )
    if "keyword_context" in missing_signals or "source_summary" in missing_signals:
        calls.append(
            {
                "tool": "search_source_chunks",
                "why": "Search raw source text for follow-up language that is not covered by structured rows.",
                "arguments": {"query": query_text, "filters": {"limit": 10}},
            }
        )
    if not calls:
        calls.append(
            {
                "tool": "expand_query_context",
                "why": "Inspect the accumulated evidence bundle and source coverage before answering.",
                "arguments": {"include_source_details": True, "max_sources": 8},
            }
        )
    return calls


async def assess_evidence_coverage(
    *,
    slack_channel_id: str,
    slack_thread_ts: str,
    query_text: str,
) -> dict[str, object]:
    session_payload = await load_thread_session_payload(
        slack_channel_id=slack_channel_id,
        slack_thread_ts=slack_thread_ts,
        create=True,
    )
    evidence_ids = _uuid_strings(list(session_payload.get("accumulated_evidence_ids") or []))
    signals = extract_follow_up_signals(query_text)
    required_fields = list(signals["required_fields"])

    async with SessionFactory() as session:
        rows = await _load_evidence_rows(session, evidence_ids)

    covered_fields: set[str] = set()
    for evidence_item, source_document, property_record in rows:
        covered_fields.update(_coverage_fields_for_row(evidence_item, source_document, property_record))

    missing_signals = [field for field in required_fields if field not in covered_fields]
    confidence = Decimal("0.0000") if not required_fields else Decimal(len(required_fields) - len(missing_signals)) / Decimal(len(required_fields))
    evidence_count = len(evidence_ids)
    if evidence_count == 0:
        confidence = Decimal("0.0000")

    is_sufficient = evidence_count > 0 and not missing_signals and confidence > Decimal("0.8500")
    needs_expansion = evidence_count > 0 and bool(missing_signals) and confidence >= Decimal("0.3500")
    return {
        "is_sufficient": is_sufficient,
        "needs_expansion": needs_expansion,
        "missing_signals": missing_signals,
        "confidence": f"{confidence:.4f}",
        "signals": signals,
        "covered_signals": sorted(covered_fields),
        "evidence_count": evidence_count,
        "recommended_mcp_calls": recommended_mcp_calls_for_missing(missing_signals, query_text),
    }


async def render_thread_evidence_answer(
    *,
    query_text: str,
    evidence_ids: list[str],
    coverage: dict[str, object],
) -> str:
    async with SessionFactory() as session:
        rows = await _load_evidence_rows(session, evidence_ids[:5])

    property_rows = [row[2] for row in rows if row[2] is not None]
    if not property_rows:
        return "*Follow-up from thread evidence*\nI do not have enough accumulated backend evidence in this thread yet."

    first = property_rows[0]
    facts: list[str] = []
    if first.address:
        location = first.address
        if first.market:
            location = f"{location} in {first.market}"
        facts.append(f"*Location:* {location}")
    if first.property_type and first.property_type != "unknown":
        use_case = first.property_type.replace("_", " ")
        if first.property_type == "industrial":
            use_case = "industrial or logistics use"
        elif first.property_type == "office":
            use_case = "office use"
        facts.append(f"*Likely use:* {use_case}")
    if first.sq_ft is not None:
        facts.append(f"*Size:* {first.sq_ft:,} SF")
    if first.price_per_sq_ft is not None:
        facts.append(f"*Rent:* ${first.price_per_sq_ft}/SF")
    if first.availability:
        facts.append(f"*Availability:* {first.availability}")

    if len(property_rows) > 1:
        facts.append(f"*Thread bundle:* {len(property_rows)} property records available for this follow-up.")

    missing = list(coverage.get("missing_signals") or [])
    if missing:
        facts.append(f"_Still thin on: {', '.join(map(str, missing))}._")
    return "*Follow-up from thread evidence*\n" + "\n".join(f"- {fact}" for fact in facts[:5])


async def create_thread_query_from_evidence(
    *,
    query_text: str,
    evidence_ids: list[str],
    rendered_answer: str,
    route_mode: str,
    route_confidence: Decimal,
    reason_codes: list[str],
    slack_channel_id: str | None,
    slack_user_id: str | None,
    slack_ts: str | None,
    slack_thread_ts: str | None,
    filters: dict[str, object],
    dependency_state: dict[str, object],
    model_versions: dict[str, object],
) -> dict[str, object]:
    normalized_evidence_ids = _uuid_values(evidence_ids)
    slack_context = _slack_context_payload(
        slack_channel_id=slack_channel_id,
        slack_user_id=slack_user_id,
        slack_ts=slack_ts,
        slack_thread_ts=slack_thread_ts,
    )
    filters_json = dict(filters or {})
    filters_json["slack_context"] = slack_context

    async with SessionFactory() as session:
        async with session.begin():
            query_record = Query(
                slack_channel_id=slack_channel_id,
                slack_user_id=slack_user_id,
                slack_ts=slack_ts,
                query_text=query_text,
                route_mode=route_mode,
                route_confidence=route_confidence,
                reason_codes=reason_codes,
            )
            session.add(query_record)
            await session.flush()

            snapshot = AnswerSnapshot(
                query_id=query_record.id,
                rendered_answer=rendered_answer,
                route_mode=route_mode,
                filters_json=filters_json,
                evidence_ids=normalized_evidence_ids,
                dependency_state_json=dependency_state,
                model_versions_json=model_versions,
            )
            session.add(snapshot)
            await session.flush()

            return {
                "status": "answered",
                "answer_mode": "instant_answer" if route_mode != "agent_follow_up" else "agent_mode",
                "route_mode": route_mode,
                "query_id": str(query_record.id),
                "answer_snapshot_id": str(snapshot.id),
                "reason_codes": reason_codes,
                "filters": filters_json,
                "evidence_count": len(normalized_evidence_ids),
                "matched_addresses": [],
                "citations": [],
                "comparison_table": None,
                "rendered_answer": rendered_answer,
            }


__all__ = [
    "assess_evidence_coverage",
    "create_thread_query_from_evidence",
    "extract_follow_up_signals",
    "load_thread_session_payload",
    "record_query_in_thread_session",
    "render_thread_evidence_answer",
]