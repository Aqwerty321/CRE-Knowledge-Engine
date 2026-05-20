from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import aiohttp
from sqlalchemy import select

from app.answering.query_service import answer_query, explain_query
from app.config import get_settings
from app.db.session import SessionFactory
from app.indexing import check_vector_dependencies
from app.ingestion.quality import collect_ingestion_quality_report
from app.ingestion.sample_importer import collect_database_counts
from app.models import AgentRun
from app.toolhouse import is_acceptable_live_toolhouse_outcome, run_toolhouse_deeper_review


@dataclass(frozen=True)
class GoldenEvalCase:
    name: str
    query: str
    expected_status: str = "answered"
    expected_route_mode: str | None = None
    required_addresses: tuple[str, ...] = ()
    required_source_labels: tuple[str, ...] = ()
    required_reason_codes: tuple[str, ...] = ()
    required_evidence_roles: tuple[str, ...] = ()
    min_evidence_count: int = 1
    required_dependency_state: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class DemoDryRunStep:
    name: str
    query: str
    expected_route_mode: str
    talk_track: str


GOLDEN_EVAL_CASES: tuple[GoldenEvalCase, ...] = (
    GoldenEvalCase(
        name="office_threshold",
        query="Show office buildings under $50/sq ft.",
        expected_route_mode="instant",
        required_addresses=("120 Main St", "75 Orchard Office", "17 Pine St"),
        required_source_labels=("main-street-office-flyer.pdf", "retail-office-followups.csv", "downtown-office-inventory.csv"),
        required_reason_codes=("numeric_filter",),
        min_evidence_count=3,
        required_dependency_state={"qdrant": False},
    ),
    GoldenEvalCase(
        name="harbor_conflict",
        query="Why did you use 62k sq ft for Harbor Rd?",
        expected_route_mode="hybrid",
        required_addresses=("240 Harbor Rd",),
        required_source_labels=("source-corrections.csv", "Slack message", "industrial-availability.csv"),
        required_reason_codes=("conflict_review",),
        required_evidence_roles=("selected", "supporting", "superseded"),
        min_evidence_count=3,
    ),
    GoldenEvalCase(
        name="loading_access",
        query="Find listings that mention loading access or yard space.",
        expected_route_mode="hybrid",
        required_addresses=("18 Beacon Freight", "130 Elm Ave", "64 Union Yard"),
        required_source_labels=("last-mile-industrial-watchlist.csv", "elm-ave-industrial-flyer.pdf"),
        required_reason_codes=("chunk_keyword_search",),
        min_evidence_count=3,
    ),
    GoldenEvalCase(
        name="beacon_exact_lookup",
        query="What do we know about 18 Beacon Freight?",
        expected_route_mode="instant",
        required_addresses=("18 Beacon Freight",),
        required_source_labels=("last-mile-industrial-watchlist.csv", "client-tour-notes.txt", "Slack message"),
        required_reason_codes=("exact_lookup",),
        min_evidence_count=3,
    ),
    GoldenEvalCase(
        name="industrial_average_rent",
        query="What is the average rent for industrial listings under $35/SF?",
        expected_route_mode="instant",
        required_addresses=("700 Logistics Pkwy", "18 Beacon Freight", "510 River Cold Storage"),
        required_source_labels=("broker-availability-tracker.xlsx", "last-mile-industrial-watchlist.csv"),
        required_reason_codes=("aggregation",),
        min_evidence_count=8,
    ),
    GoldenEvalCase(
        name="last_mile_tenant_fit",
        query="Which options look best for a logistics tenant under $35/SF available soon?",
        expected_route_mode="hybrid",
        required_addresses=("18 Beacon Freight", "42 Spruce Flex"),
        required_source_labels=("last-mile-industrial-watchlist.csv",),
        required_reason_codes=("local_synthesis",),
        min_evidence_count=3,
        required_dependency_state={"local_synthesis": True},
    ),
    GoldenEvalCase(
        name="structured_industrial_filter",
        query="Show industrial listings over 30k SF under $25/SF.",
        expected_route_mode="instant",
        required_addresses=("240 Harbor Rd", "700 Logistics Pkwy", "88 Foundry Ln"),
        required_source_labels=("industrial-availability.csv", "broker-availability-tracker.xlsx"),
        required_reason_codes=("structured_property_search",),
        min_evidence_count=3,
    ),
    GoldenEvalCase(
        name="data_quality",
        query="What source data is missing from the indexed corpus?",
        expected_route_mode="instant",
        required_reason_codes=("missing_data_review",),
        min_evidence_count=0,
    ),
)


DEMO_DRY_RUN_STEPS: tuple[DemoDryRunStep, ...] = (
    DemoDryRunStep(
        name="proximity",
        query="What properties do we have available near 123 Main Street?",
        expected_route_mode="instant",
        talk_track="Deterministic proximity retrieval over seeded coordinates with sourced results.",
    ),
    DemoDryRunStep(
        name="office_filter",
        query="Show office buildings under $50/sq ft.",
        expected_route_mode="instant",
        talk_track="Structured Postgres filter that excludes the higher-priced office candidate.",
    ),
    DemoDryRunStep(
        name="loading_access",
        query="Find whse opts with trk court and trlr parking.",
        expected_route_mode="hybrid",
        talk_track="Hybrid retrieval over shorthand and operational language in listing text and field notes.",
    ),
    DemoDryRunStep(
        name="tenant_fit",
        query="Which options look best for a logistics tenant under $35/SF available soon?",
        expected_route_mode="hybrid",
        talk_track="Local tenant-fit synthesis over price, timing, size, logistics language, and source quality.",
    ),
    DemoDryRunStep(
        name="average_rent",
        query="What is the average rent for industrial listings under $35/SF?",
        expected_route_mode="instant",
        talk_track="Structured aggregation over deduped industrial records from files and Slack-shaped notes.",
    ),
    DemoDryRunStep(
        name="harbor_conflict",
        query="Why did you use 62k sq ft for Harbor Rd?",
        expected_route_mode="hybrid",
        talk_track="Conflict handling that prefers fresher correction evidence and exposes superseded facts.",
    ),
)


def _source_label(evidence_item: dict[str, Any]) -> str:
    source_document = evidence_item.get("source_document") if isinstance(evidence_item.get("source_document"), dict) else {}
    if source_document.get("file_name"):
        return str(source_document["file_name"])
    if source_document.get("source_type") == "slack_message":
        return "Slack message"
    return str(source_document.get("source_type") or "unknown")


def _evidence_addresses(explain_payload: dict[str, Any]) -> list[str]:
    addresses: list[str] = []
    for item in explain_payload.get("evidence", []):
        property_record = item.get("property_record") if isinstance(item.get("property_record"), dict) else {}
        address = property_record.get("address")
        if isinstance(address, str) and address and address not in addresses:
            addresses.append(address)
    return addresses


def _append_missing_subset_failures(
    failures: list[str],
    *,
    label: str,
    required: tuple[str, ...],
    actual: list[str] | set[str],
) -> None:
    missing = [value for value in required if value not in actual]
    if missing:
        failures.append(f"missing {label}: {', '.join(missing)}")


def _has_required_role_order(evidence_roles: list[str], required_roles: tuple[str, ...]) -> bool:
    if not required_roles:
        return True
    if not evidence_roles or evidence_roles[0] != required_roles[0]:
        return False

    next_required_index = 1
    for evidence_role in evidence_roles[1:]:
        if next_required_index >= len(required_roles):
            return True
        if evidence_role == required_roles[next_required_index]:
            next_required_index += 1
    return next_required_index >= len(required_roles)


async def _evaluate_case(case: GoldenEvalCase) -> dict[str, object]:
    answer_payload = await answer_query(case.query)
    explain_payload = await explain_query(str(answer_payload.get("query_id") or ""))
    failures: list[str] = []

    if answer_payload.get("status") != case.expected_status:
        failures.append(f"status expected {case.expected_status}, got {answer_payload.get('status')}")
    if case.expected_route_mode is not None and answer_payload.get("route_mode") != case.expected_route_mode:
        failures.append(f"route_mode expected {case.expected_route_mode}, got {answer_payload.get('route_mode')}")
    if explain_payload.get("status") != "explained":
        failures.append(f"explain_query expected explained, got {explain_payload.get('status')}")

    answer_evidence_count = int(answer_payload.get("evidence_count") or 0)
    explain_evidence = list(explain_payload.get("evidence", []))
    if answer_evidence_count < case.min_evidence_count:
        failures.append(f"evidence_count expected at least {case.min_evidence_count}, got {answer_evidence_count}")
    if len(explain_evidence) != answer_evidence_count:
        failures.append(f"explain evidence count {len(explain_evidence)} did not match answer count {answer_evidence_count}")

    snapshot = explain_payload.get("answer_snapshot") if isinstance(explain_payload.get("answer_snapshot"), dict) else {}
    snapshot_evidence_ids = [str(value) for value in snapshot.get("evidence_ids", [])]
    explain_evidence_ids = [str(item.get("evidence_id")) for item in explain_evidence if item.get("evidence_id")]
    if snapshot_evidence_ids != explain_evidence_ids:
        failures.append("snapshot evidence_ids do not replay in explain_query order")

    matched_addresses = list(answer_payload.get("matched_addresses") or [])
    evidence_addresses = _evidence_addresses(explain_payload)
    all_addresses = list(dict.fromkeys([*matched_addresses, *evidence_addresses]))
    _append_missing_subset_failures(failures, label="addresses", required=case.required_addresses, actual=all_addresses)

    source_labels = [_source_label(item) for item in explain_evidence]
    _append_missing_subset_failures(failures, label="source labels", required=case.required_source_labels, actual=source_labels)

    reason_codes = set(str(value) for value in answer_payload.get("reason_codes", [])) | set(
        str(value) for value in explain_payload.get("reason_codes", [])
    )
    _append_missing_subset_failures(failures, label="reason codes", required=case.required_reason_codes, actual=reason_codes)

    evidence_roles = [str(item.get("evidence_role")) for item in explain_evidence if item.get("evidence_role")]
    if case.required_evidence_roles and not _has_required_role_order(evidence_roles, case.required_evidence_roles):
        failures.append(f"evidence roles expected {list(case.required_evidence_roles)}, got {evidence_roles}")

    dependency_state = dict(snapshot.get("dependency_state") or {})
    for key, expected_value in case.required_dependency_state.items():
        if dependency_state.get(key) != expected_value:
            failures.append(f"dependency_state.{key} expected {expected_value!r}, got {dependency_state.get(key)!r}")

    return {
        "name": case.name,
        "query": case.query,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "query_id": answer_payload.get("query_id"),
        "answer_status": answer_payload.get("status"),
        "route_mode": answer_payload.get("route_mode"),
        "evidence_count": answer_evidence_count,
        "evidence_ids": explain_evidence_ids,
        "matched_addresses": matched_addresses,
        "source_labels": source_labels,
        "reason_codes": sorted(reason_codes),
        "dependency_state": dependency_state,
    }


async def run_golden_evals(case_names: list[str] | None = None) -> dict[str, object]:
    selected_names = set(case_names or [])
    cases = [case for case in GOLDEN_EVAL_CASES if not selected_names or case.name in selected_names]
    missing_cases = sorted(selected_names - {case.name for case in GOLDEN_EVAL_CASES})
    results = [await _evaluate_case(case) for case in cases]
    failed = [result for result in results if result["status"] != "passed"]
    status = "passed" if not failed and not missing_cases and results else "failed"
    return {
        "status": status,
        "case_count": len(results),
        "passed_count": len(results) - len(failed),
        "failed_count": len(failed),
        "missing_cases": missing_cases,
        "cases": results,
    }


def _text_preview(value: object, *, limit: int = 360) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 3]}..."


async def _run_demo_dry_run_step(step: DemoDryRunStep) -> dict[str, object]:
    answer_payload = await answer_query(step.query)
    query_id = str(answer_payload.get("query_id") or "")
    replay_payload = await replay_query(query_id) if query_id else {"status": "missing_query_id"}
    replay_checks = dict(replay_payload.get("replay_checks") or {})
    failures: list[str] = []

    if answer_payload.get("status") != "answered":
        failures.append(f"answer status expected answered, got {answer_payload.get('status')}")
    if answer_payload.get("route_mode") != step.expected_route_mode:
        failures.append(f"route_mode expected {step.expected_route_mode}, got {answer_payload.get('route_mode')}")
    if replay_payload.get("status") != "replayed":
        failures.append(f"replay status expected replayed, got {replay_payload.get('status')}")
    if replay_checks.get("snapshot_evidence_ids_match_explain_order") is not True:
        failures.append("snapshot evidence IDs did not replay in explain order")
    if replay_checks.get("missing_source_document_evidence_ids"):
        failures.append("one or more evidence items is missing a source document")

    evidence = list(replay_payload.get("evidence", []))
    source_summaries = [str(item.get("source_summary")) for item in evidence if item.get("source_summary")]
    return {
        "name": step.name,
        "status": "passed" if not failures else "failed",
        "failures": failures,
        "query": step.query,
        "talk_track": step.talk_track,
        "query_id": query_id or None,
        "replay_command": f"uv run cre-cli replay-query {query_id}" if query_id else None,
        "answer_status": answer_payload.get("status"),
        "route_mode": answer_payload.get("route_mode"),
        "expected_route_mode": step.expected_route_mode,
        "reason_codes": answer_payload.get("reason_codes", []),
        "evidence_count": answer_payload.get("evidence_count"),
        "matched_addresses": answer_payload.get("matched_addresses", []),
        "source_summaries": source_summaries,
        "rendered_answer_preview": _text_preview(answer_payload.get("rendered_answer")),
        "replay_checks": replay_checks,
    }


async def demo_dry_run(*, include_public_callback: bool = False, live_toolhouse: bool = False) -> dict[str, object]:
    started_at = datetime.now(UTC)
    preflight = await demo_doctor(
        include_public_callback=include_public_callback,
        include_toolhouse_smoke=False,
    )
    steps = [await _run_demo_dry_run_step(step) for step in DEMO_DRY_RUN_STEPS]

    toolhouse_step: dict[str, object]
    if not live_toolhouse:
        toolhouse_step = {
            "name": "toolhouse_look_deeper",
            "status": "skipped",
            "reason": "Run with --live-toolhouse to prove the external Toolhouse path.",
        }
    else:
        loading_step = next((step for step in steps if step["name"] == "loading_access"), None)
        query_id = str(loading_step.get("query_id") if loading_step else "")
        if not query_id:
            toolhouse_step = {
                "name": "toolhouse_look_deeper",
                "status": "failed",
                "failures": ["loading_access query did not produce a query_id"],
            }
        else:
            try:
                deeper_payload = await run_toolhouse_deeper_review(query_id)
                passed = is_acceptable_live_toolhouse_outcome(deeper_payload)
                toolhouse_step = {
                    "name": "toolhouse_look_deeper",
                    "status": "passed" if passed else "failed",
                    "failures": [] if passed else ["Toolhouse deeper review did not complete as a validated live run"],
                    "query_id": query_id,
                    "agent_run_id": deeper_payload.get("agent_run_id"),
                    "toolhouse_agent_id": deeper_payload.get("toolhouse_agent_id"),
                    "toolhouse_run_id": deeper_payload.get("toolhouse_run_id"),
                    "validation": dict(deeper_payload.get("validation") or {}),
                    "dependency_state": dict(deeper_payload.get("dependency_state") or {}),
                    "fallback": deeper_payload.get("toolhouse_fallback", False),
                    "rendered_answer_preview": _text_preview(deeper_payload.get("rendered_answer")),
                }
            except Exception as exc:  # noqa: BLE001
                toolhouse_step = {
                    "name": "toolhouse_look_deeper",
                    "status": "failed",
                    "failures": [str(exc)],
                    "query_id": query_id,
                }

    failed_steps = [step for step in steps if step.get("status") != "passed"]
    toolhouse_failed = toolhouse_step.get("status") == "failed"
    passed = preflight.get("status") == "ready" and not failed_steps and not toolhouse_failed
    finished_at = datetime.now(UTC)
    return {
        "status": "passed" if passed else "failed",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "preflight_status": preflight.get("status"),
        "preflight_failed_check_count": preflight.get("failed_check_count"),
        "step_count": len(steps),
        "failed_step_count": len(failed_steps) + (1 if toolhouse_failed else 0),
        "slack_prompt_sequence": [step.query for step in DEMO_DRY_RUN_STEPS],
        "recommended_replay_commands": [step["replay_command"] for step in steps if step.get("replay_command")],
        "steps": steps,
        "toolhouse_step": toolhouse_step,
        "preflight": preflight,
    }


def _uuid_or_none(value: str) -> UUID | None:
    try:
        return UUID(str(value))
    except ValueError:
        return None


async def _agent_runs_for_query(query_id: str) -> list[dict[str, object]]:
    parsed_query_id = _uuid_or_none(query_id)
    if parsed_query_id is None:
        return []
    async with SessionFactory() as session:
        rows = list(
            (
                await session.execute(
                    select(AgentRun)
                    .where(AgentRun.query_id == parsed_query_id)
                    .order_by(AgentRun.created_at)
                )
            ).scalars()
        )
    return [
        {
            "id": str(row.id),
            "provider": row.provider,
            "status": row.status,
            "answer_mode": row.answer_mode,
            "toolhouse_agent_id": row.toolhouse_agent_id,
            "toolhouse_run_id": row.toolhouse_run_id,
            "allowed_evidence_ids": list(row.allowed_evidence_ids_json or []),
            "cited_evidence_ids": list(row.cited_evidence_ids_json or []),
            "validation": dict(row.validation_json or {}),
            "dependency_state": dict(row.dependency_state_json or {}),
            "fallback_reason": row.fallback_reason,
            "rendered_answer": row.rendered_answer,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
        }
        for row in rows
    ]


async def replay_query(query_id: str) -> dict[str, object]:
    explain_payload = await explain_query(query_id)
    if explain_payload.get("status") != "explained":
        return explain_payload

    snapshot = explain_payload.get("answer_snapshot") if isinstance(explain_payload.get("answer_snapshot"), dict) else {}
    snapshot_ids = [str(value) for value in snapshot.get("evidence_ids", [])]
    evidence = list(explain_payload.get("evidence", []))
    evidence_ids = [str(item.get("evidence_id")) for item in evidence if item.get("evidence_id")]
    source_documents_missing = [item.get("evidence_id") for item in evidence if not item.get("source_document")]
    field_detail_count = sum(len(item.get("field_details", [])) for item in evidence)

    return {
        "status": "replayed",
        "query_id": explain_payload["query_id"],
        "query_text": explain_payload.get("query_text"),
        "route_mode": explain_payload.get("route_mode"),
        "reason_codes": explain_payload.get("reason_codes", []),
        "created_at": explain_payload.get("created_at"),
        "answer_snapshot": snapshot,
        "rendered_answer": snapshot.get("rendered_answer"),
        "decision_summary": explain_payload.get("decision_summary"),
        "evidence_count": len(evidence),
        "evidence": evidence,
        "agent_runs": await _agent_runs_for_query(query_id),
        "replay_checks": {
            "snapshot_evidence_ids_match_explain_order": snapshot_ids == evidence_ids,
            "snapshot_evidence_count": len(snapshot_ids),
            "explained_evidence_count": len(evidence_ids),
            "missing_source_document_evidence_ids": source_documents_missing,
            "field_detail_count": field_detail_count,
            "dependency_state": snapshot.get("dependency_state", {}),
            "model_versions": snapshot.get("model_versions", {}),
        },
    }


async def _http_health_check(url: str) -> dict[str, object]:
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                return {
                    "status": "ok" if response.status == 200 else "failed",
                    "url": url,
                    "http_status": response.status,
                }
    except (aiohttp.ClientError, TimeoutError) as exc:
        return {"status": "failed", "url": url, "error": str(exc)}


def _check_status(name: str, passed: bool, **details: object) -> dict[str, object]:
    return {"name": name, "status": "ok" if passed else "failed", **details}


async def demo_doctor(*, include_public_callback: bool = True, include_toolhouse_smoke: bool = False) -> dict[str, object]:
    settings = get_settings()
    checks: list[dict[str, object]] = []

    try:
        counts = await collect_database_counts()
        checks.append(
            _check_status(
                "database_counts",
                counts.get("source_documents", 0) >= 14
                and counts.get("chunks", 0) >= 14
                and counts.get("property_records", 0) >= 14
                and counts.get("slack_source_posts", 0) >= 1,
                counts=counts,
            )
        )
    except Exception as exc:  # noqa: BLE001
        checks.append(_check_status("database_counts", False, error=str(exc)))

    dependency_checks = await check_vector_dependencies()
    required_dependency_names = ["qdrant"]
    if settings.vector_search_enabled or settings.vector_index_on_import:
        required_dependency_names.extend(["embedding", "rerank"])
    if settings.ocr_enabled:
        required_dependency_names.append("ocr")
    checks.append(
        _check_status(
            "local_dependencies",
            all(dependency_checks.get(name) == "ok" for name in required_dependency_names),
            dependency_checks=dependency_checks,
            required=required_dependency_names,
        )
    )

    audit_payload = await collect_ingestion_quality_report()
    readiness = dict(audit_payload.get("toolhouse_readiness") or {})
    checks.append(
        _check_status(
            "data_audit",
            readiness.get("status") == "ready_for_bounded_agent",
            toolhouse_readiness=readiness,
            source_document_count=audit_payload.get("source_document_count"),
            property_record_count=audit_payload.get("property_record_count"),
            conflict_group_count=len(audit_payload.get("conflict_groups", [])),
        )
    )

    golden_payload = await run_golden_evals()
    checks.append(
        _check_status(
            "golden_evals",
            golden_payload.get("status") == "passed",
            case_count=golden_payload.get("case_count"),
            passed_count=golden_payload.get("passed_count"),
            failed_count=golden_payload.get("failed_count"),
            failures=[case for case in golden_payload.get("cases", []) if case.get("status") != "passed"],
        )
    )

    toolhouse_configured = bool(settings.toolhouse_api_key and settings.toolhouse_agent_id and settings.toolhouse_mcp_bearer_token)
    checks.append(
        _check_status(
            "toolhouse_config",
            toolhouse_configured,
            agent_id=settings.toolhouse_agent_id,
            mcp_configured=bool(settings.toolhouse_mcp_bearer_token),
        )
    )

    if include_public_callback:
        if settings.public_callback_url:
            public_check = await _http_health_check(f"{settings.public_callback_url.rstrip('/')}/health/deps")
            public_check["name"] = "public_callback"
            checks.append(public_check)
        else:
            checks.append(_check_status("public_callback", False, error="CLOUDFLARE_PUBLIC_CALLBACK_URL is not configured"))

    if include_toolhouse_smoke:
        if not toolhouse_configured:
            checks.append(_check_status("toolhouse_smoke", False, error="Toolhouse config is incomplete"))
        else:
            try:
                answer_payload = await answer_query("Find listings that mention loading access or yard space.")
                deeper_payload = await run_toolhouse_deeper_review(str(answer_payload["query_id"]))
                checks.append(
                    _check_status(
                        "toolhouse_smoke",
                        is_acceptable_live_toolhouse_outcome(deeper_payload),
                        query_id=deeper_payload.get("query_id"),
                        toolhouse_run_id=deeper_payload.get("toolhouse_run_id"),
                        validation=dict(deeper_payload.get("validation") or {}),
                        dependency_state=dict(deeper_payload.get("dependency_state") or {}),
                        fallback=deeper_payload.get("toolhouse_fallback", False),
                    )
                )
            except Exception as exc:  # noqa: BLE001
                checks.append(_check_status("toolhouse_smoke", False, error=str(exc)))

    failed = [check for check in checks if check.get("status") != "ok"]
    return {
        "status": "ready" if not failed else "needs_attention",
        "failed_check_count": len(failed),
        "check_count": len(checks),
        "checks": checks,
    }