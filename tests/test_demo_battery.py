from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete
from sqlalchemy.exc import SQLAlchemyError

from app.answering.query_service import answer_query, explain_query
from app.db.session import SessionFactory, engine
from app.evaluation import replay_query, run_golden_evals
from app.ingestion.sample_importer import import_sample_data
from app.models import AnswerSnapshot, EvidenceItem, Query, SourceDocument


def _ensure_schema() -> None:
    command.upgrade(Config("alembic.ini"), "head")


async def _prepare_query_database() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AnswerSnapshot))
            await session.execute(delete(EvidenceItem))
            await session.execute(delete(Query))
            await session.execute(delete(SourceDocument))
    await import_sample_data(Path("sample-data"), include_generated=False)


@pytest.fixture
def async_runner() -> asyncio.Runner:
    with asyncio.Runner() as runner:
        yield runner
        runner.run(engine.dispose())


@pytest.fixture
def prepared_query_db(async_runner: asyncio.Runner) -> None:
    try:
        _ensure_schema()
        async_runner.run(_prepare_query_database())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres not available for demo battery tests: {exc}")


@pytest.mark.golden
def test_expanded_exact_lookup_reads_beacon_profile(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("What do we know about 18 Beacon Freight?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert payload["matched_addresses"] == ["18 Beacon Freight"]
    assert payload["evidence_count"] >= 3
    assert "36,000 SF" in payload["rendered_answer"]
    assert "120 ft truck court" in payload["rendered_answer"]
    assert "trailer parking" in payload["rendered_answer"]
    assert "last-mile-industrial-watchlist.csv" in payload["rendered_answer"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))
    replay_payload = async_runner.run(replay_query(payload["query_id"]))

    assert explain_payload["decision_summary"]["query_constructor"]["sort"] is None
    assert any(item["source_document"]["file_name"] == "client-tour-notes.txt" for item in explain_payload["evidence"])
    first_record = explain_payload["evidence"][0]["property_record"]
    assert first_record["dock_doors"] == 2
    assert first_record["truck_court_depth_ft"] == 120
    assert "trailer parking" in str(first_record["loading_access"])
    assert replay_payload["status"] == "replayed"
    assert replay_payload["replay_checks"]["snapshot_evidence_ids_match_explain_order"] is True


@pytest.mark.golden
def test_expanded_available_soon_filter_returns_deeper_shortlist(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Show industrial listings available soon under $35/SF."))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert payload["filters"]["query_constructor"]["conditions"]
    assert {"18 Beacon Freight", "42 Spruce Flex", "240 Harbor Rd", "88 Foundry Ln"}.issubset(
        set(payload["matched_addresses"])
    )
    assert "Direct match" in payload["rendered_answer"]
    assert payload["comparison_table"] is not None


@pytest.mark.golden
def test_expanded_average_rent_aggregation_uses_deduped_industrial_set(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("What is the average rent for industrial listings under $35/SF?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "Average asking rent is $24.78/SF" in payload["rendered_answer"]
    assert payload["evidence_count"] == 8
    assert {"700 Logistics Pkwy", "18 Beacon Freight", "510 River Cold Storage"}.issubset(
        set(payload["matched_addresses"])
    )

    explain_payload = async_runner.run(explain_query(payload["query_id"]))

    assert explain_payload["decision_summary"]["query_constructor"]["base_table"] == "property_records"
    assert "aggregation" in set(explain_payload["reason_codes"])


@pytest.mark.golden
def test_noisy_truck_court_query_uses_hybrid_polyfuzz_stack(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Find whse opts with trk court and trlr parking."))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "hybrid"
    assert "18 Beacon Freight" in payload["matched_addresses"]
    assert "hybrid_local_retrieval" in payload["reason_codes"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))
    dependency_state = explain_payload["answer_snapshot"]["dependency_state"]

    assert dependency_state["retrieval_mode"] == "hybrid_lexical_fuzzy"
    assert "polyfuzz" in dependency_state["retrieval_layers"]
    assert set(dependency_state["retrieval_contributors"]) & {"bm25", "polyfuzz", "tfidf_char"}
    matched_fields = {
        term
        for item in explain_payload["evidence"]
        for term in list(item.get("matched_fields") or [])
    }
    assert {"truck court", "trailer parking"}.issubset(matched_fields)


@pytest.mark.golden
def test_tenant_fit_shortlist_uses_expanded_last_mile_evidence(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Which options look best for a logistics tenant under $35/SF available soon?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "hybrid"
    assert payload["matched_addresses"][0] == "18 Beacon Freight"
    assert {"18 Beacon Freight", "42 Spruce Flex"}.issubset(set(payload["matched_addresses"]))
    assert "Best local shortlist" in payload["rendered_answer"]
    assert "*Look deeper*" in payload["rendered_answer"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))

    assert explain_payload["decision_summary"]["retrieval_mode"] == "structured_tenant_fit"
    assert explain_payload["evidence"][0]["evidence_role"] == "selected"
    assert explain_payload["evidence"][0]["source_document"]["file_name"] == "last-mile-industrial-watchlist.csv"


@pytest.mark.golden
def test_common_broad_inventory_query_returns_sourced_snapshot(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("list all properties"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "broad_inventory" in payload["reason_codes"]
    assert payload["evidence_count"] >= 10
    assert {"120 Main St", "18 Beacon Freight", "240 Harbor Rd"}.issubset(set(payload["matched_addresses"]))
    assert "Inventory snapshot" in payload["rendered_answer"]
    assert "Use *Look deeper*" in payload["rendered_answer"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))

    assert explain_payload["decision_summary"]["query_constructor"]["base_table"] == "property_records"
    assert explain_payload["decision_summary"]["query_constructor"]["limit"] >= 25


@pytest.mark.golden
def test_common_sort_only_query_uses_dynamic_structured_search(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("show me the cheapest properties"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "sort_price" in payload["reason_codes"]
    assert payload["filters"]["query_constructor"]["sort"] == "price_asc"
    assert "Direct match" in payload["rendered_answer"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))
    prices = [
        float(item["property_record"]["price_per_sq_ft"])
        for item in explain_payload["evidence"]
        if item.get("property_record") and item["property_record"].get("price_per_sq_ft") is not None
    ]
    assert prices == sorted(prices)


@pytest.mark.golden
def test_expanded_golden_eval_cases_cover_demo_modes(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(
        run_golden_evals(
            case_names=["beacon_exact_lookup", "industrial_average_rent", "last_mile_tenant_fit"]
        )
    )

    assert payload["status"] == "passed"
    assert payload["case_count"] == 3
    assert payload["failed_count"] == 0


@pytest.mark.golden
def test_unsupported_query_records_failed_mode_without_evidence(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Forecast cap rates for 2029 from market vibes."))

    assert payload["status"] == "unsupported"
    assert payload["answer_mode"] == "instant_answer"
    assert payload["route_mode"] == "failed"
    assert payload["evidence_count"] == 0
    assert "Unsupported query" in payload["rendered_answer"]
    assert "Look deeper" in payload["rendered_answer"]
