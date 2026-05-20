from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, select
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


async def _prepare_generated_query_database() -> None:
    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(delete(AnswerSnapshot))
            await session.execute(delete(EvidenceItem))
            await session.execute(delete(Query))
            await session.execute(delete(SourceDocument))
    await import_sample_data(Path("sample-data"), include_generated=True)


async def _load_query_artifacts(query_id: str) -> tuple[Query, list[EvidenceItem], AnswerSnapshot | None]:
    async with SessionFactory() as session:
        query_record = await session.get(Query, UUID(query_id))
        assert query_record is not None
        evidence_result = await session.execute(select(EvidenceItem).where(EvidenceItem.query_id == query_record.id))
        snapshot = await session.scalar(select(AnswerSnapshot).where(AnswerSnapshot.query_id == query_record.id))
        return query_record, list(evidence_result.scalars()), snapshot


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
        pytest.skip(f"Postgres not available for golden answer tests: {exc}")


@pytest.fixture
def prepared_generated_query_db(async_runner: asyncio.Runner) -> None:
    try:
        _ensure_schema()
        async_runner.run(_prepare_generated_query_database())
    except (OSError, SQLAlchemyError) as exc:
        pytest.skip(f"Postgres not available for generated-corpus answer tests: {exc}")


@pytest.mark.golden
def test_proximity_query_returns_ranked_cited_results(prepared_query_db: None, async_runner: asyncio.Runner) -> None:
    payload = async_runner.run(answer_query("What properties do we have available near 123 Main Street?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert payload["matched_addresses"][:2] == ["120 Main St", "130 Elm Ave"]
    assert payload["evidence_count"] == 3
    assert "main-street-office-flyer.pdf" in payload["rendered_answer"]
    assert "elm-ave-industrial-flyer.pdf" in payload["rendered_answer"]

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert query_record.route_mode == "instant"
    assert len(evidence_items) == payload["evidence_count"]
    assert all(item.source_summary for item in evidence_items)
    assert snapshot is not None
    assert snapshot.route_mode == "instant"
    assert len(snapshot.evidence_ids) == payload["evidence_count"]


@pytest.mark.golden
def test_proximity_explain_query_surfaces_query_scoped_distance_details(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("What properties do we have available near 123 Main Street?"))

    explain_payload = async_runner.run(explain_query(answer_payload["query_id"]))

    assert explain_payload["status"] == "explained"
    assert explain_payload["decision_summary"]["anchor_address"] == "123 Main Street"
    assert explain_payload["answer_snapshot"]["filters"]["query_evidence_details"]
    assert all(item["distance_km"] is not None for item in explain_payload["evidence"])
    assert all(item["anchor_address"] == "123 Main Street" for item in explain_payload["evidence"])
    assert all("distance-ranked from 123 Main Street" in str(item["selection_reason"]) for item in explain_payload["evidence"])


@pytest.mark.golden
def test_proximity_query_can_prefilter_candidates_with_structured_constraints(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Near 123 Main Street, which industrial options have truck court or trailer parking?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "structured_property_search" in payload["reason_codes"]
    assert payload["matched_addresses"][0] == "18 Beacon Freight"
    assert "120 Main St" not in payload["matched_addresses"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))

    assert explain_payload["answer_snapshot"]["filters"]["proximity_query_filters"]["property_types"] == ["industrial"]
    evidence_property_types = [
        item["property_record"]["property_type"]
        for item in explain_payload["evidence"]
        if item.get("property_record")
    ]
    assert evidence_property_types
    assert set(evidence_property_types) == {"industrial"}


@pytest.mark.golden
def test_office_threshold_query_excludes_high_price_listing(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Show office buildings under $50/sq ft."))

    assert payload["status"] == "answered"
    assert payload["matched_addresses"] == ["120 Main St", "75 Orchard Office", "17 Pine St"]
    assert "900 North Loop" not in payload["rendered_answer"]
    assert payload["evidence_count"] == 3

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert "numeric_filter" in query_record.reason_codes
    assert len(evidence_items) == 3
    assert snapshot is not None
    assert snapshot.filters_json["price_per_sq_ft_lt"] == "50"


@pytest.mark.golden
def test_john_industrial_aggregation_sums_deduped_sources(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("What is the total square footage of industrial properties in John's file or notes?"))

    assert payload["status"] == "answered"
    assert payload["matched_addresses"] == ["130 Elm Ave", "18 Beacon Freight", "42 Spruce Flex", "64 Union Yard"]
    assert "111,500 SF" in payload["rendered_answer"]
    assert payload["evidence_count"] == 4

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert "aggregation" in query_record.reason_codes
    assert len(evidence_items) == 4
    assert snapshot is not None
    assert snapshot.filters_json["slack_user_name"] == "John"


@pytest.mark.golden
def test_source_lookup_query_returns_file_and_slack_citations(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Where did the $42/SF number for 120 Main come from?"))

    assert payload["status"] == "answered"
    assert payload["matched_addresses"] == ["120 Main St"]
    assert payload["evidence_count"] == 2
    assert any("main-street-office-flyer.pdf" in citation for citation in payload["citations"])
    assert any("Slack message" in citation for citation in payload["citations"])

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert "source_lookup" in query_record.reason_codes
    assert len(evidence_items) == 2
    assert snapshot is not None
    assert snapshot.route_mode == "instant"


@pytest.mark.golden
def test_explain_query_returns_replayable_trust_receipt(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show office buildings under $50/sq ft."))

    explain_payload = async_runner.run(explain_query(answer_payload["query_id"]))

    assert explain_payload["status"] == "explained"
    assert explain_payload["query_id"] == answer_payload["query_id"]
    assert explain_payload["route_mode"] == "instant"
    assert "numeric_filter" in explain_payload["reason_codes"]
    assert explain_payload["answer_snapshot"]["filters"]["price_per_sq_ft_lt"] == "50"
    assert explain_payload["answer_snapshot"]["rendered_answer"] == answer_payload["rendered_answer"]
    assert explain_payload["answer_snapshot"]["dependency_state"]["qdrant"] is False
    assert explain_payload["evidence_count"] == 3
    assert len(explain_payload["evidence"]) == 3

    first_evidence = explain_payload["evidence"][0]
    assert first_evidence["source_summary"]
    assert first_evidence["source_document"]["file_name"] == "main-street-office-flyer.pdf"
    assert first_evidence["property_record"]["address"] == "120 Main St"
    assert first_evidence["field_details"]
    assert any(detail["field_name"] == "price_per_sq_ft" for detail in first_evidence["field_details"])


@pytest.mark.golden
def test_eval_golden_validates_expected_sources_and_evidence_order(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(run_golden_evals(case_names=["office_threshold", "harbor_conflict"]))

    assert payload["status"] == "passed"
    assert payload["case_count"] == 2
    assert payload["failed_count"] == 0

    office_case = next(case for case in payload["cases"] if case["name"] == "office_threshold")
    assert office_case["evidence_ids"]
    assert office_case["matched_addresses"] == ["120 Main St", "75 Orchard Office", "17 Pine St"]
    assert "main-street-office-flyer.pdf" in office_case["source_labels"]

    harbor_case = next(case for case in payload["cases"] if case["name"] == "harbor_conflict")
    assert harbor_case["route_mode"] == "hybrid"
    assert harbor_case["source_labels"] == ["source-corrections.csv", "Slack message", "industrial-availability.csv"]


@pytest.mark.golden
def test_replay_query_projects_snapshot_evidence_and_checks(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Show office buildings under $50/sq ft."))

    replay_payload = async_runner.run(replay_query(answer_payload["query_id"]))

    assert replay_payload["status"] == "replayed"
    assert replay_payload["query_text"] == "Show office buildings under $50/sq ft."
    assert replay_payload["rendered_answer"] == answer_payload["rendered_answer"]
    assert replay_payload["replay_checks"]["snapshot_evidence_ids_match_explain_order"] is True
    assert replay_payload["replay_checks"]["missing_source_document_evidence_ids"] == []
    assert replay_payload["replay_checks"]["field_detail_count"] >= 2
    assert replay_payload["agent_runs"] == []


@pytest.mark.golden
def test_explain_query_handles_unknown_query_id(prepared_query_db: None, async_runner: asyncio.Runner) -> None:
    explain_payload = async_runner.run(explain_query("00000000-0000-0000-0000-000000000000"))

    assert explain_payload["status"] == "not_found"
    assert explain_payload["message"] == "No stored query exists for that ID."


@pytest.mark.golden
def test_harbor_change_query_returns_hybrid_conflict_answer(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Did anything change for Harbor Rd yesterday?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "hybrid"
    assert payload["matched_addresses"] == ["240 Harbor Rd"]
    assert payload["evidence_count"] == 3
    assert "62,000 SF" in payload["rendered_answer"]
    assert "58,000 SF" in payload["rendered_answer"]
    assert "source-corrections.csv" in payload["rendered_answer"]
    assert "industrial-availability.csv" in payload["rendered_answer"]

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert query_record.route_mode == "hybrid"
    assert "change_detection" in query_record.reason_codes
    assert len(evidence_items) == 3
    assert snapshot is not None
    assert snapshot.dependency_state_json["keyword_fallback"] is True
    assert snapshot.dependency_state_json["retrieval_mode"] == "keyword_conflict_review"


@pytest.mark.golden
def test_harbor_why_query_explain_shows_selected_and_superseded_evidence(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Why did you use 62k sq ft for Harbor Rd?"))

    assert answer_payload["status"] == "answered"
    assert answer_payload["route_mode"] == "hybrid"
    assert answer_payload["evidence_count"] == 3
    assert "freshness" in answer_payload["rendered_answer"]

    explain_payload = async_runner.run(explain_query(answer_payload["query_id"]))

    assert explain_payload["status"] == "explained"
    assert explain_payload["route_mode"] == "hybrid"
    assert explain_payload["answer_snapshot"]["dependency_state"]["keyword_fallback"] is True
    assert explain_payload["decision_summary"]["selected_sq_ft"] == 62000
    assert explain_payload["decision_summary"]["superseded_sq_ft"] == [58000]
    assert "freshest correction" in explain_payload["decision_summary"]["selection_reason"]

    evidence_roles = [item["evidence_role"] for item in explain_payload["evidence"]]
    assert evidence_roles == ["selected", "supporting", "superseded"]
    assert explain_payload["evidence"][0]["source_document"]["file_name"] == "source-corrections.csv"
    assert explain_payload["evidence"][1]["source_document"]["source_type"] == "slack_message"
    assert explain_payload["evidence"][2]["source_document"]["file_name"] == "industrial-availability.csv"
    assert explain_payload["evidence"][2]["selection_reason"] == "older conflicting value outranked by fresher correction evidence"


@pytest.mark.golden
def test_loading_access_query_returns_hybrid_keyword_results(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Find listings that mention loading access or yard space."))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "hybrid"
    assert {"18 Beacon Freight", "130 Elm Ave", "64 Union Yard"}.issubset(set(payload["matched_addresses"]))
    assert payload["evidence_count"] >= 3
    assert "loading dock" in payload["rendered_answer"]
    assert "yard" in payload["rendered_answer"]

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert query_record.route_mode == "hybrid"
    assert "chunk_keyword_search" in query_record.reason_codes
    assert len(evidence_items) >= 3
    assert snapshot is not None
    assert snapshot.dependency_state_json["keyword_fallback"] is True
    assert snapshot.dependency_state_json["retrieval_mode"] == "hybrid_lexical_fuzzy"
    assert "bm25" in snapshot.dependency_state_json["retrieval_contributors"]
    assert "polyfuzz" in snapshot.dependency_state_json["retrieval_layers"]


@pytest.mark.golden
def test_loading_access_explain_query_shows_keyword_chunk_matches(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    answer_payload = async_runner.run(answer_query("Find listings that mention loading access or yard space."))

    explain_payload = async_runner.run(explain_query(answer_payload["query_id"]))

    assert explain_payload["status"] == "explained"
    assert explain_payload["route_mode"] == "hybrid"
    assert explain_payload["answer_snapshot"]["dependency_state"]["keyword_fallback"] is True
    assert explain_payload["decision_summary"]["retrieval_mode"] == "hybrid_lexical_fuzzy"
    assert {"18 Beacon Freight", "130 Elm Ave", "64 Union Yard"}.issubset(
        set(explain_payload["decision_summary"]["selected_addresses"])
    )
    assert "hybrid lexical" in explain_payload["decision_summary"]["selection_reason"]

    evidence_by_address = {
        item["property_record"]["address"]: item
        for item in explain_payload["evidence"]
        if item.get("property_record")
    }
    beacon_evidence = evidence_by_address["18 Beacon Freight"]
    elm_evidence = evidence_by_address["130 Elm Ave"]
    assert beacon_evidence["evidence_role"] == "result"
    assert beacon_evidence["source_document"]["file_name"] in {
        "last-mile-industrial-watchlist.csv",
        "client-tour-notes.txt",
    }
    assert "truck court" in beacon_evidence["selection_reason"]
    assert "trailer parking" in beacon_evidence["selection_reason"]
    assert "loading dock" in elm_evidence["chunk"]["text_preview"]


@pytest.mark.golden
def test_noisy_loading_access_query_uses_alias_and_fuzzy_retrieval(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Find whse options with dock doors or truck court."))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "hybrid"
    assert {"18 Beacon Freight", "130 Elm Ave", "64 Union Yard"}.issubset(set(payload["matched_addresses"]))
    assert "hybrid_local_retrieval" in payload["reason_codes"]

    _query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert snapshot is not None
    assert snapshot.dependency_state_json["retrieval_mode"] == "hybrid_lexical_fuzzy"
    assert "dock doors" in snapshot.filters_json["expanded_terms"]
    matched_fields = {field for item in evidence_items for field in item.matched_fields}
    assert {"dock doors", "truck court", "trailer parking"}.issubset(matched_fields)
    assert set(snapshot.dependency_state_json["retrieval_contributors"]) & {"bm25", "polyfuzz", "tfidf_char"}


@pytest.mark.golden
def test_generic_structured_query_constructor_handles_numeric_filters(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Show industrial listings over 30k SF under $25/SF."))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "structured_property_search" in payload["reason_codes"]
    assert "query_constructor" in payload["filters"]
    assert {"240 Harbor Rd", "700 Logistics Pkwy", "88 Foundry Ln"}.issubset(set(payload["matched_addresses"]))
    assert "Direct match" in payload["rendered_answer"]
    assert payload["comparison_table"] is not None
    assert payload["comparison_table"]["columns"] == ["Addr", "SF", "Rent", "Avail"]
    assert len(payload["comparison_table"]["rows"]) >= 2

    explain_payload = async_runner.run(explain_query(payload["query_id"]))

    assert explain_payload["status"] == "explained"
    assert explain_payload["decision_summary"]["query_constructor"]["base_table"] == "property_records"
    assert any(condition["field"] == "property_records.sq_ft" for condition in explain_payload["decision_summary"]["query_constructor"]["conditions"])


@pytest.mark.golden
def test_generic_exact_lookup_returns_property_profile(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("What do we know about 700 Logistics Pkwy?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert payload["matched_addresses"] == ["700 Logistics Pkwy"]
    assert "120,000 SF" in payload["rendered_answer"]
    assert "broker-availability-tracker.xlsx" in payload["rendered_answer"]
    assert payload["comparison_table"] is None


@pytest.mark.golden
def test_location_lookup_subject_avoids_yard_keyword_drift(
    prepared_generated_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("what do u know about hudson yard"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "structured_property_search" in payload["reason_codes"]
    assert "chunk_keyword_search" not in payload["reason_codes"]
    assert "Hudson Yards" in payload["rendered_answer"]
    assert "loading access or yard space" not in payload["rendered_answer"].lower()

    explain_payload = async_runner.run(explain_query(payload["query_id"]))
    conditions = explain_payload["decision_summary"]["query_constructor"]["conditions"]

    assert any(
        condition["field"] == "property_records.location_fields" and "hudson yards" in condition["value"]
        for condition in conditions
    )
    assert all(condition["field"] != "property_records.infrastructure" for condition in conditions)


@pytest.mark.golden
def test_property_name_lookup_subject_prefers_aurora_campus_records(
    prepared_generated_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("tell me about aurora campus"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "lookup_subject_property" in payload["reason_codes"]
    assert "Aurora Campus" in payload["rendered_answer"]
    assert payload["matched_addresses"] == ["7935 River Ln, Denver", "6606 River Ln, Denver"]
    assert "8546 Orchard Row" not in payload["rendered_answer"]

    explain_payload = async_runner.run(explain_query(payload["query_id"]))
    conditions = explain_payload["decision_summary"]["query_constructor"]["conditions"]

    assert any(
        condition["field"] == "property_records.property_name_or_listing_id" and "aurora campus" in condition["value"]
        for condition in conditions
    )


@pytest.mark.golden
def test_no_results_answer_explains_filters_and_closest_matches(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Show office buildings under $35/sq ft."))

    assert payload["status"] == "no_results"
    assert payload["missing_data_explanation"] is not None
    assert "Closest matches after relaxing numeric/date filters" in payload["rendered_answer"]
    assert payload["filters"]["missing_data_explanation"]["blocking_filters"]


@pytest.mark.golden
def test_data_quality_query_explains_missing_structured_coverage(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("What source data is missing from the indexed corpus?"))

    assert payload["status"] == "answered"
    assert payload["evidence_count"] == 0
    assert "Data-quality pass" in payload["rendered_answer"]
    assert "source(s) have text but no extracted property rows" in payload["rendered_answer"]
    assert payload["data_quality_report"]["sources_without_properties"]


@pytest.mark.golden
def test_cap_rate_query_returns_generated_corpus_matches(
    prepared_generated_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Show industrial listings with cap rate over 6%."))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert "structured_property_search" in payload["reason_codes"]
    assert payload["matched_addresses"]
    assert "cap rate" in payload["rendered_answer"].lower()

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert query_record.route_mode == "instant"
    assert "cap_rate_lower_bound" in query_record.reason_codes
    assert len(evidence_items) >= 1
    assert snapshot is not None
    assert snapshot.filters_json["cap_rate_gte"] == "0.06"
    assert any("cap_rate" in item.matched_fields for item in evidence_items)


@pytest.mark.golden
def test_sea_facing_query_returns_generated_corpus_matches(
    prepared_generated_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("what are some of the sea facing properties"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert payload["evidence_count"] >= 1
    assert payload["matched_addresses"]
    assert "frontage" in payload["rendered_answer"].lower()

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert query_record.route_mode == "instant"
    assert "facing_detected" in query_record.reason_codes
    assert len(evidence_items) >= 1
    assert snapshot is not None
    assert set(snapshot.filters_json["facing"]) >= {"sea_facing", "waterfront"}


@pytest.mark.golden
def test_inventory_overview_summarizes_generated_corpus(
    prepared_generated_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("what are the types of properties"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    summary = payload["filters"]["inventory_summary"]
    assert summary["total_count"] >= 2400
    assert summary["generated_corpus_count"] == 2400
    assert "data center" in payload["rendered_answer"]
    assert "generated large-corpus rows" in payload["rendered_answer"]
    assert "current slice" not in payload["rendered_answer"]

    legacy_addresses = {
        "120 Main St",
        "130 Elm Ave",
        "18 Beacon Freight",
        "240 Harbor Rd",
        "88 Foundry Ln",
    }
    assert any(address not in legacy_addresses for address in payload["matched_addresses"])


@pytest.mark.golden
def test_facing_summary_query_lists_available_facing_types(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("what are the kinds of facing that we have available"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "instant"
    assert payload["evidence_count"] == 4
    assert "Facing summary" in payload["rendered_answer"]
    assert "south" in payload["rendered_answer"].lower()
    assert "west" in payload["rendered_answer"].lower()
    assert "2 listing(s)" in payload["rendered_answer"]
    assert payload["comparison_table"] is not None
    assert payload["comparison_table"]["columns"] == ["Facing", "Count"]
    assert payload["comparison_table"]["rows"] == [["west", "2"], ["east", "1"], ["south", "1"]]

    query_record, evidence_items, snapshot = async_runner.run(_load_query_artifacts(payload["query_id"]))

    assert query_record.route_mode == "instant"
    assert "aggregation" in query_record.reason_codes
    assert len(evidence_items) == 4
    assert snapshot is not None
    assert snapshot.filters_json["aggregate"] == "facet_counts"
    assert snapshot.filters_json["aggregate_field"] == "facing"


@pytest.mark.golden
def test_tenant_fit_query_uses_local_synthesis_before_toolhouse(
    prepared_query_db: None,
    async_runner: asyncio.Runner,
) -> None:
    payload = async_runner.run(answer_query("Which options look best for a logistics tenant under $35/SF?"))

    assert payload["status"] == "answered"
    assert payload["route_mode"] == "hybrid"
    assert "local_synthesis" in payload["reason_codes"]
    assert "Best local shortlist" in payload["rendered_answer"]
    assert "*18 Beacon Freight*" in payload["rendered_answer"]
    assert "*Look deeper*" in payload["rendered_answer"]
    assert payload["filters"]["query_constructor"]["sort"] == "tenant_fit"

    explain_payload = async_runner.run(explain_query(payload["query_id"]))

    assert explain_payload["decision_summary"]["retrieval_mode"] == "structured_tenant_fit"
    assert explain_payload["evidence"][0]["evidence_role"] == "selected"