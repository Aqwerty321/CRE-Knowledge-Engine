from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Awaitable, Callable

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
from sqlalchemy.exc import SQLAlchemyError

from app.answering.query_service import answer_query
from app.db.session import SessionFactory, engine
from app.ingestion.sample_importer import import_sample_data
from app.models import AgentRun, AnswerSnapshot, EvidenceItem, Query, SourceDocument
from app.toolhouse.client import ToolhouseRunResult, run_toolhouse_deeper_review
from app.toolhouse import (
    aggregate_properties_tool,
    audit_data_tool,
    describe_backend_schema_tool,
    explain_evidence_tool,
    expand_query_context_tool,
    expand_query_evidence_tool,
    find_property_conflicts_tool,
    get_source_detail_tool,
    get_property_timeline_tool,
    local_deeper_review_tool,
    nearby_properties_tool,
    rank_properties_tool,
    search_properties_tool,
    search_source_chunks_tool,
    summarize_inventory_tool,
)
from app.toolhouse.local_agent import validate_agent_response


class FakeToolhouseClient:
    def __init__(
        self,
        response_payload: dict[str, object],
        before_response: Callable[[str, dict[str, object]], Awaitable[None]] | None = None,
    ) -> None:
        self.response_payload = response_payload
        self.before_response = before_response

    async def send_message(self, message: str, *, run_id: str | None = None) -> ToolhouseRunResult:
        assert "Use CRE Backend MCP first" in message
        if self.before_response is not None:
            await self.before_response(message, self.response_payload)
        return ToolhouseRunResult(
            agent_id="fake-agent",
            run_id="fake-run",
            raw_response="{}",
            response_payload=self.response_payload,
        )


class SequencedFakeToolhouseClient:
    def __init__(self, responses: list[ToolhouseRunResult]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, str | None]] = []

    async def send_message(self, message: str, *, run_id: str | None = None) -> ToolhouseRunResult:
        assert "Use CRE Backend MCP first" in message
        self.calls.append({"message": message, "run_id": run_id})
        assert self._responses
        return self._responses.pop(0)


def _ensure_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


async def _prepare_database() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AnswerSnapshot))
            await session.execute(delete(EvidenceItem))
            await session.execute(delete(AgentRun))
            await session.execute(delete(Query))
            await session.execute(delete(SourceDocument))
    await import_sample_data(Path("sample-data"), include_generated=False)


async def _load_agent_run(agent_run_id: str) -> AgentRun | None:
    async with SessionFactory() as session:
        return await session.get(AgentRun, agent_run_id)


@pytest.fixture
def async_runner() -> asyncio.Runner:
    with asyncio.Runner() as runner:
        yield runner
        runner.run(engine.dispose())


@pytest.fixture
def prepared_db(async_runner: asyncio.Runner) -> None:
    try:
        _ensure_schema()
        async_runner.run(_prepare_database())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres not available for Toolhouse tool tests: {exc}")


@pytest.mark.golden
def test_toolhouse_tools_are_evidence_bound_and_query_constructor_ready(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))

    evidence_payload = async_runner.run(explain_evidence_tool(str(answer_payload["query_id"])))
    deeper_payload = async_runner.run(local_deeper_review_tool(str(answer_payload["query_id"])))
    search_payload = async_runner.run(
        search_properties_tool(
            {
                "property_types": ["industrial"],
                "price_per_sq_ft_lt": "25",
                "sq_ft_gte": 30000,
                "limit": 5,
            }
        )
    )
    source_id = search_payload["results"][0]["source_document"]["id"]
    source_payload = async_runner.run(get_source_detail_tool(str(source_id)))
    aggregate_payload = async_runner.run(
        aggregate_properties_tool(
            {
                "property_types": ["industrial"],
                "price_per_sq_ft_lt": "25",
                "sq_ft_gte": 30000,
            },
            group_by="property_type",
            metrics=["count", "sum_sq_ft", "avg_price_per_sq_ft"],
        )
    )
    chunk_payload = async_runner.run(
        search_source_chunks_tool(
            "loading dock yard logistics",
            {"property_types": ["industrial"], "limit": 5},
        )
    )
    nearby_payload = async_runner.run(
        nearby_properties_tool(
            {"lat": "40.750700", "lng": "-73.996700", "label": "120 Main St"},
            3.0,
            {"property_types": ["office"], "limit": 5},
        )
    )
    schema_payload = async_runner.run(describe_backend_schema_tool())
    context_payload = async_runner.run(expand_query_context_tool(str(answer_payload["query_id"]), max_sources=3))
    expansion_payload = async_runner.run(
        expand_query_evidence_tool(
            str(answer_payload["query_id"]),
            {"property_types": ["office"], "limit": 2},
            reason="compare industrial answer against nearby office alternatives",
        )
    )
    summary_payload = async_runner.run(summarize_inventory_tool({"limit": 12}, query_id=str(answer_payload["query_id"])))
    rank_payload = async_runner.run(
        rank_properties_tool(
            {"property_types": ["industrial"], "sq_ft_gte": 30000, "limit": 5},
            objective="logistics tenant fit",
            keywords=["loading", "yard", "logistics"],
            query_id=str(answer_payload["query_id"]),
        )
    )
    timeline_payload = async_runner.run(get_property_timeline_tool("88 Foundry Ln", query_id=str(answer_payload["query_id"])))
    conflicts_payload = async_runner.run(find_property_conflicts_tool({"limit": 100}, query_id=str(answer_payload["query_id"]), limit=5))
    audit_payload = async_runner.run(audit_data_tool())

    assert evidence_payload["status"] == "ready"
    assert evidence_payload["payload"]["allowed_evidence_ids"]
    assert evidence_payload["payload"]["evidence_context"]["policy_version"] == "evidence-context-v2"
    assert "expand_query_evidence" in {
        tool["name"] for tool in evidence_payload["payload"]["evidence_context"]["available_backend_mcp_tools"]
    }
    assert deeper_payload["payload"]["validation"]["valid"] is True
    assert search_payload["query_constructor"]["base_table"] == "property_records"
    assert search_payload["result_count"] >= 3
    assert source_payload["status"] == "ok"
    assert source_payload["chunks"]
    assert aggregate_payload["status"] == "ok"
    assert aggregate_payload["matched_record_count"] >= 1
    assert aggregate_payload["rows"][0]["metrics"]["count"] >= 1
    assert chunk_payload["status"] == "ok"
    assert chunk_payload["result_count"] >= 1
    assert nearby_payload["status"] == "ok"
    assert nearby_payload["result_count"] >= 1
    assert nearby_payload["spatial_backend"]["status"] in {"ready", "numeric_fallback", "unavailable"}
    assert schema_payload["status"] == "ok"
    assert schema_payload["property_filters"]["dock_doors_gte"] == "integer minimum dock/loading door count"
    assert "property-record snapshots" in schema_payload["property_filters"]["locations"]
    assert "cap_rate_desc" in schema_payload["property_filters"]["sort"]
    assert schema_payload["geospatial"]["fallback"].startswith("geo_lat")
    assert schema_payload["location_resolution"]["backend_query_packages"].startswith("When Toolhouse starts from a backend query package")
    assert "country_codes" in schema_payload["qdrant_payload"]["rich_metadata"]
    assert "state_provinces" in schema_payload["qdrant_payload"]["rich_metadata"]
    assert "geo_points" in schema_payload["qdrant_payload"]["rich_metadata"]
    assert any(example["filters"].get("cap_rate_gte") == "0.06" for example in schema_payload["safe_examples"] if example["tool"] == "search_properties")
    assert "expand_query_evidence" in {tool["name"] for tool in schema_payload["available_backend_mcp_tools"]}
    assert "rank_properties" in {tool["name"] for tool in schema_payload["available_backend_mcp_tools"]}
    assert context_payload["status"] == "ok"
    assert context_payload["source_detail_count"] >= 1
    assert expansion_payload["status"] == "ok"
    assert expansion_payload["allowed_evidence_ids_total"]
    assert summary_payload["status"] == "ok"
    assert summary_payload["ranked_slices"]["cheapest"]["result_count"] >= 1
    assert rank_payload["status"] == "ok"
    assert rank_payload["results"][0]["evidence_id"]
    assert timeline_payload["status"] == "ok"
    assert timeline_payload["event_count"] >= 1
    assert conflicts_payload["status"] == "ok"
    assert conflicts_payload["conflict_count"] >= 1
    assert audit_payload["status"] == "ok"
    assert audit_payload["toolhouse_readiness"]["status"] == "ready_for_bounded_agent"


@pytest.mark.golden
def test_toolhouse_can_expand_allowed_evidence_before_validation(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("What do we know about 120 Main?"))
    initial_evidence_payload = async_runner.run(explain_evidence_tool(str(answer_payload["query_id"])))
    initial_allowed_ids = set(initial_evidence_payload["payload"]["allowed_evidence_ids"])
    cited_ids: list[str] = []

    async def expand_before_response(message: str, response_payload: dict[str, object]) -> None:
        message_payload = json.loads(message)
        expansion_payload = await expand_query_evidence_tool(
            str(message_payload["query_id"]),
            {"property_types": ["industrial"], "limit": 2},
            reason="Toolhouse requested comparable industrial evidence for a broader read.",
        )
        new_ids = [
            evidence_id
            for evidence_id in expansion_payload["allowed_evidence_ids_total"]
            if evidence_id not in initial_allowed_ids
        ]
        assert new_ids
        cited_ids[:] = [new_ids[0]]
        response_payload["cited_evidence_ids"] = cited_ids

    deeper_payload = async_runner.run(
        run_toolhouse_deeper_review(
            str(answer_payload["query_id"]),
            client=FakeToolhouseClient(
                {
                    "status": "answered",
                    "rendered_answer": "Toolhouse expanded the evidence set and cited the backend-minted ID.",
                    "cited_evidence_ids": [],
                    "confidence_label": "medium",
                    "reasoning_summary": "Used expand_query_evidence to add comparable backend evidence before citing it.",
                    "mcp_tools_used": ["explain_evidence", "expand_query_evidence"],
                    "toolhouse_integrations_used": [],
                    "slack_tools_used": [],
                    "external_sources_consulted": [],
                    "unsupported_claims_dropped": [],
                    "missing_data": [],
                    "suggested_followups": [],
                },
                before_response=expand_before_response,
            ),
        )
    )

    assert deeper_payload["status"] == "answered"
    assert deeper_payload["validation"]["valid"] is True
    assert deeper_payload["cited_evidence_ids"] == cited_ids
    assert cited_ids[0] in deeper_payload["escalation_payload"]["allowed_evidence_ids"]

    agent_run = async_runner.run(_load_agent_run(str(deeper_payload["agent_run_id"])))

    assert agent_run is not None
    assert cited_ids[0] in agent_run.allowed_evidence_ids_json
    assert agent_run.cited_evidence_ids_json == cited_ids


@pytest.mark.golden
def test_toolhouse_deeper_review_accepts_valid_agent_citations(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))
    evidence_payload = async_runner.run(explain_evidence_tool(str(answer_payload["query_id"])))
    evidence_id = evidence_payload["payload"]["allowed_evidence_ids"][0]

    deeper_payload = async_runner.run(
        run_toolhouse_deeper_review(
            str(answer_payload["query_id"]),
            client=FakeToolhouseClient(
                {
                    "status": "answered",
                    "rendered_answer": "Toolhouse-backed answer.",
                    "cited_evidence_ids": [evidence_id],
                    "confidence_label": "high",
                    "reasoning_summary": "Grounded in explain_evidence.",
                    "mcp_tools_used": ["explain_evidence"],
                    "toolhouse_integrations_used": [],
                    "slack_tools_used": [],
                    "external_sources_consulted": [],
                    "unsupported_claims_dropped": [],
                    "missing_data": [],
                    "suggested_followups": [],
                }
            ),
        )
    )

    assert deeper_payload["status"] == "answered"
    assert deeper_payload["rendered_answer"] == "Toolhouse-backed answer."
    assert deeper_payload["validation"]["valid"] is True
    assert deeper_payload["toolhouse_run_id"] == "fake-run"
    assert deeper_payload["agent_run_id"]

    agent_run = async_runner.run(_load_agent_run(str(deeper_payload["agent_run_id"])))

    assert agent_run is not None
    assert agent_run.provider == "toolhouse"
    assert agent_run.status == "answered"
    assert agent_run.toolhouse_agent_id == "fake-agent"
    assert agent_run.toolhouse_run_id == "fake-run"
    assert agent_run.validation_json["valid"] is True
    assert agent_run.allowed_evidence_ids_json
    assert agent_run.cited_evidence_ids_json == [evidence_id]
    assert agent_run.response_payload_json["rendered_answer"] == "Toolhouse-backed answer."
    assert agent_run.rendered_answer == "Toolhouse-backed answer."


@pytest.mark.golden
def test_toolhouse_deeper_review_retries_empty_response_once(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))
    client = SequencedFakeToolhouseClient(
        [
            ToolhouseRunResult(
                agent_id="fake-agent",
                run_id="fake-run",
                raw_response="",
                response_payload=None,
                parse_error="empty_response",
            ),
            ToolhouseRunResult(
                agent_id="fake-agent",
                run_id="fake-run",
                raw_response=json.dumps(
                    {
                        "status": "needs_more_evidence",
                        "rendered_answer": "Need one more backend evidence pass before answering.",
                        "cited_evidence_ids": [],
                        "confidence_label": "low",
                        "reasoning_summary": "The first Toolhouse body was empty, but the retry returned a valid JSON response.",
                        "mcp_tools_used": ["explain_evidence"],
                        "toolhouse_integrations_used": [],
                        "slack_tools_used": [],
                        "external_sources_consulted": [],
                        "unsupported_claims_dropped": [],
                        "missing_data": ["Additional backend evidence for a stronger answer."],
                        "suggested_followups": [],
                    }
                ),
                response_payload={
                    "status": "needs_more_evidence",
                    "rendered_answer": "Need one more backend evidence pass before answering.",
                    "cited_evidence_ids": [],
                    "confidence_label": "low",
                    "reasoning_summary": "The first Toolhouse body was empty, but the retry returned a valid JSON response.",
                    "mcp_tools_used": ["explain_evidence"],
                    "toolhouse_integrations_used": [],
                    "slack_tools_used": [],
                    "external_sources_consulted": [],
                    "unsupported_claims_dropped": [],
                    "missing_data": ["Additional backend evidence for a stronger answer."],
                    "suggested_followups": [],
                },
            ),
        ]
    )

    deeper_payload = async_runner.run(
        run_toolhouse_deeper_review(
            str(answer_payload["query_id"]),
            client=client,
        )
    )

    assert deeper_payload["status"] == "needs_more_evidence"
    assert deeper_payload.get("toolhouse_fallback", False) is False
    assert deeper_payload["validation"]["valid"] is True
    assert deeper_payload["dependency_state"]["toolhouse"] is True
    assert deeper_payload["dependency_state"]["toolhouse_empty_response_retry"] is True
    assert len(client.calls) == 2
    assert client.calls[0]["run_id"] is None
    assert client.calls[1]["run_id"] == "fake-run"

    agent_run = async_runner.run(_load_agent_run(str(deeper_payload["agent_run_id"])))

    assert agent_run is not None
    assert agent_run.provider == "toolhouse"
    assert agent_run.toolhouse_run_id == "fake-run"
    assert agent_run.validation_json["valid"] is True
    assert agent_run.response_payload_json["status"] == "needs_more_evidence"


@pytest.mark.golden
def test_search_properties_tool_can_mint_query_scoped_evidence(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))
    search_payload = async_runner.run(
        search_properties_tool(
            {
                "property_types": ["industrial"],
                "price_per_sq_ft_lt": "25",
                "sq_ft_gte": 30000,
                "limit": 5,
            },
            query_id=str(answer_payload["query_id"]),
        )
    )

    assert search_payload["status"] == "ok"
    assert search_payload["query_id"] == str(answer_payload["query_id"])
    assert search_payload["evidence_expansion"]["status"] == "ok"
    assert any(result["evidence_id"] for result in search_payload["results"])
    assert "backend-minted" in search_payload["evidence_note"]


@pytest.mark.golden
def test_search_source_chunks_tool_can_mint_query_scoped_evidence(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))
    chunk_payload = async_runner.run(
        search_source_chunks_tool(
            "loading dock yard logistics",
            {"property_types": ["industrial"], "limit": 5},
            query_id=str(answer_payload["query_id"]),
        )
    )

    assert chunk_payload["status"] == "ok"
    assert chunk_payload["query_id"] == str(answer_payload["query_id"])
    assert chunk_payload["evidence_expansion"]["status"] == "ok"
    assert any(result["evidence_id"] for result in chunk_payload["results"])
    assert "backend-minted" in chunk_payload["evidence_note"]


@pytest.mark.golden
def test_find_property_conflicts_tool_inherits_query_scope_filters(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show office buildings under $50/sq ft."))

    conflicts_payload = async_runner.run(
        find_property_conflicts_tool(
            {"price_per_sq_ft_lt": "50", "limit": 100},
            query_id=str(answer_payload["query_id"]),
            limit=5,
        )
    )

    assert conflicts_payload["query_scope_filters_applied"]["property_types"] == ["office"]
    assert conflicts_payload["conflict_count"] == 0
    conditions = list(conflicts_payload["query_constructor"]["conditions"])
    assert any(condition["field"] == "property_records.property_type" and condition["value"] == ["office"] for condition in conditions)


def test_validate_agent_response_rejects_answer_without_citations() -> None:
    validation = validate_agent_response(
        allowed_evidence_ids={"11111111-1111-4111-8111-111111111111"},
        response_payload={
            "status": "answered",
            "rendered_answer": "Looks good, but cites nothing.",
            "cited_evidence_ids": [],
            "confidence_label": "high",
            "reasoning_summary": "No citation support.",
            "mcp_tools_used": ["explain_evidence"],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [],
            "unsupported_claims_dropped": [],
            "missing_data": [],
            "suggested_followups": [],
        },
    )

    assert validation["valid"] is False
    assert "answered responses must cite at least one allowed evidence ID" in validation["schema_errors"]


def test_validate_agent_response_accepts_mcp_unavailable_without_citations() -> None:
    validation = validate_agent_response(
        allowed_evidence_ids=set(),
        response_payload={
            "status": "mcp_unavailable",
            "rendered_answer": "MCP is unavailable, so no CRE facts were returned.",
            "cited_evidence_ids": [],
            "confidence_label": "low",
            "reasoning_summary": "Required MCP access was unavailable.",
            "mcp_tools_used": [],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [],
            "unsupported_claims_dropped": ["All CRE claims were withheld."],
            "missing_data": ["CRE Backend MCP access."],
            "suggested_followups": ["Reconnect MCP and retry."],
        },
    )

    assert validation["valid"] is True


def test_validate_agent_response_accepts_valid_optional_comparison_table() -> None:
    validation = validate_agent_response(
        allowed_evidence_ids={"11111111-1111-4111-8111-111111111111"},
        response_payload={
            "status": "answered",
            "rendered_answer": "*Deeper read*\n- 240 Harbor Rd leads.",
            "comparison_table": {
                "title": "Quick comparison",
                "columns": ["Addr", "SF", "Rent", "Avail"],
                "rows": [
                    ["240 Harbor Rd", "62,000 SF", "$18.00/SF", "Aug 2026"],
                    ["88 Foundry Ln", "44,000 SF", "$21.50/SF", "Q2 2026"],
                ],
            },
            "cited_evidence_ids": ["11111111-1111-4111-8111-111111111111"],
            "confidence_label": "high",
            "reasoning_summary": "Grounded in explain_evidence.",
            "mcp_tools_used": ["explain_evidence"],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [],
            "unsupported_claims_dropped": [],
            "missing_data": [],
            "suggested_followups": [],
        },
    )

    assert validation["valid"] is True


def test_validate_agent_response_accepts_coordinator_tool_names() -> None:
    validation = validate_agent_response(
        allowed_evidence_ids={"11111111-1111-4111-8111-111111111111"},
        response_payload={
            "status": "answered",
            "rendered_answer": "Ranked with backend coordinator tools.",
            "cited_evidence_ids": ["11111111-1111-4111-8111-111111111111"],
            "confidence_label": "medium",
            "reasoning_summary": "Used inventory, ranking, timeline, and conflict tools before answering.",
            "mcp_tools_used": [
                "explain_evidence",
                "summarize_inventory",
                "rank_properties",
                "get_property_timeline",
                "find_property_conflicts",
            ],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [],
            "unsupported_claims_dropped": [],
            "missing_data": [],
            "suggested_followups": [],
        },
    )

    assert validation["valid"] is True


def test_validate_agent_response_rejects_malformed_comparison_table() -> None:
    validation = validate_agent_response(
        allowed_evidence_ids={"11111111-1111-4111-8111-111111111111"},
        response_payload={
            "status": "answered",
            "rendered_answer": "Table is malformed.",
            "comparison_table": {
                "columns": ["Addr", "SF", "Rent"],
                "rows": [["240 Harbor Rd", "62,000 SF"]],
            },
            "cited_evidence_ids": ["11111111-1111-4111-8111-111111111111"],
            "confidence_label": "high",
            "reasoning_summary": "Grounded in explain_evidence.",
            "mcp_tools_used": ["explain_evidence"],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [],
            "unsupported_claims_dropped": [],
            "missing_data": [],
            "suggested_followups": [],
        },
    )

    assert validation["valid"] is False
    assert "comparison_table.rows must be an array with at least 2 rows" in validation["schema_errors"]


def test_validate_agent_response_rejects_unsupported_tools_and_external_source_roles() -> None:
    validation = validate_agent_response(
        allowed_evidence_ids={"11111111-1111-4111-8111-111111111111"},
        response_payload={
            "status": "answered",
            "rendered_answer": "This uses unsupported surface area.",
            "cited_evidence_ids": ["11111111-1111-4111-8111-111111111111"],
            "confidence_label": "medium",
            "reasoning_summary": "Claims to use an unsupported tool.",
            "mcp_tools_used": ["search_properties", "write_database"],
            "toolhouse_integrations_used": [],
            "slack_tools_used": [],
            "external_sources_consulted": [
                {"title": "Unknown site", "url": "https://example.com", "role": "primary_fact_source"}
            ],
            "unsupported_claims_dropped": [],
            "missing_data": [],
            "suggested_followups": [],
        },
    )

    assert validation["valid"] is False
    assert "mcp_tools_used contains unsupported tool names: write_database" in validation["schema_errors"]
    assert "external_sources_consulted[0].role is unsupported" in validation["schema_errors"]


@pytest.mark.golden
def test_toolhouse_deeper_review_falls_back_on_invalid_agent_contract(
    prepared_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))

    deeper_payload = async_runner.run(
        run_toolhouse_deeper_review(
            str(answer_payload["query_id"]),
            client=FakeToolhouseClient(
                {
                    "status": "answered",
                    "rendered_answer": "Toolhouse answer without citations.",
                    "cited_evidence_ids": [],
                    "confidence_label": "high",
                    "reasoning_summary": "Missing citation support.",
                    "mcp_tools_used": ["explain_evidence"],
                    "toolhouse_integrations_used": [],
                    "slack_tools_used": [],
                    "external_sources_consulted": [],
                    "unsupported_claims_dropped": [],
                    "missing_data": [],
                    "suggested_followups": [],
                }
            ),
        )
    )

    assert deeper_payload["status"] == "answered"
    assert deeper_payload["toolhouse_fallback"] is True
    assert deeper_payload["validation"]["valid"] is True
    assert deeper_payload["toolhouse_validation"]["valid"] is False
    assert "Deeper review" in deeper_payload["rendered_answer"]
    assert "*Evidence checked:*" in deeper_payload["rendered_answer"]
    assert deeper_payload["agent_run_id"]

    agent_run = async_runner.run(_load_agent_run(str(deeper_payload["agent_run_id"])))

    assert agent_run is not None
    assert agent_run.provider == "local_fallback"
    assert agent_run.status == "answered"
    assert agent_run.toolhouse_run_id == "fake-run"
    assert agent_run.validation_json["valid"] is False
    assert agent_run.response_payload_json["rendered_answer"] == "Toolhouse answer without citations."
    assert agent_run.fallback_reason is not None
    assert agent_run.fallback_reason.startswith("validation_error:")
