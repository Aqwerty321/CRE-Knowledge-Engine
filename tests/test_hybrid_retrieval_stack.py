from __future__ import annotations

import asyncio

import app.routing.query_constructor as query_constructor

from app.retrieval.hybrid_pipeline import LocalHybridRetrievalPipeline
from app.retrieval.retrieval_config import HybridRetrievalConfig
from app.retrieval.retrieval_types import RetrievalDocument
from app.routing.query_router import build_query_plan


CONCEPT = "loading_access_or_yard_space"


def _config(*, bm25_enabled: bool = True) -> HybridRetrievalConfig:
    return HybridRetrievalConfig.from_mapping(
        {
            "concepts": {
                CONCEPT: [
                    "loading dock",
                    "dock doors",
                    "yard access",
                    "shared yard",
                    "trailer storage",
                    "truck court",
                    "trailer parking",
                ]
            },
            "aliases": {
                "whse": ["warehouse", "industrial"],
                "dock doors": ["loading dock"],
                "truck court": ["shared yard", "trailer storage"],
                "trailer parking": ["trailer storage", "yard access"],
            },
            "enabled_retrievers": {
                "bm25": bm25_enabled,
                "substring": True,
                "polyfuzz": True,
                "tfidf_char": True,
                "qdrant_vector": False,
                "rerank": False,
            },
            "limit": 3,
            "candidate_limit": 3,
            "fuzzy_min_score": 0.40,
            "tfidf_min_score": 0.01,
        }
    )


def _documents() -> list[RetrievalDocument]:
    return [
        RetrievalDocument(
            id="elm",
            text="130 Elm Ave is an industrial warehouse with loading dock doors and direct yard access.",
            metadata={"address": "130 Elm Ave"},
        ),
        RetrievalDocument(
            id="union",
            text="64 Union Yard has shared yard circulation, trailer storage, and outdoor staging.",
            metadata={"address": "64 Union Yard"},
        ),
        RetrievalDocument(
            id="main",
            text="120 Main St is an office listing with conference rooms and no industrial loading features.",
            metadata={"address": "120 Main St"},
        ),
    ]


def _run_pipeline(query: str, *, config: HybridRetrievalConfig | None = None, concept: str | None = CONCEPT):
    pipeline = LocalHybridRetrievalPipeline(config or _config())
    return asyncio.run(pipeline.retrieve(query, _documents(), concept=concept, limit=3))


def test_hybrid_pipeline_exact_match_prefers_lexical_candidate() -> None:
    result = _run_pipeline("need a loading dock with yard access")

    assert result.candidates[0].document.id == "elm"
    assert {item.retriever for item in result.candidates[0].contributions} >= {"bm25", "substring"}
    assert "loading dock" in result.candidates[0].matched_terms


def test_hybrid_pipeline_typo_match_uses_fuzzy_layers() -> None:
    result = _run_pipeline("lodng dok yrd acses", concept=None)

    assert result.candidates[0].document.id == "elm"
    contributors = {item.retriever for item in result.candidates[0].contributions}
    assert contributors & {"polyfuzz", "tfidf_char"}


def test_hybrid_pipeline_shorthand_alias_expansion() -> None:
    result = _run_pipeline("need whse w dock doors")

    assert result.candidates[0].document.id == "elm"
    assert "dock doors" in result.expansion.matched_aliases
    assert "whse" not in result.expansion.matched_aliases


def test_hybrid_pipeline_semantic_paraphrase_via_configured_aliases() -> None:
    result = _run_pipeline("truck court with trailer parking")

    assert result.candidates[0].document.id == "union"
    assert "trailer storage" in result.candidates[0].matched_terms


def test_hybrid_pipeline_falls_back_when_bm25_is_disabled() -> None:
    result = _run_pipeline("loading dock yard", config=_config(bm25_enabled=False))

    assert result.candidates[0].document.id == "elm"
    assert result.layer_status["bm25"] == "disabled"
    assert {item.retriever for item in result.candidates[0].contributions} & {"substring", "polyfuzz", "tfidf_char"}


def test_router_uses_alias_config_for_noisy_loading_queries() -> None:
    plan = build_query_plan("Find whse options with dock doors or truck court")

    assert plan.route_mode == "hybrid"
    assert plan.query_type == "loading_access_search"
    assert plan.filters["retrieval_mode"] == "hybrid_lexical_fuzzy"
    assert "hybrid_local_retrieval" in plan.reason_codes


def test_router_prefers_structured_plan_when_explicit_numeric_or_geo_filters_exist() -> None:
    plan = build_query_plan("Show industrial for sale under $8m with at least 4 dock doors and map links")

    assert plan.route_mode == "instant"
    assert plan.query_type == "generic_property_search"
    assert plan.filters["sale_price_lt"] == "8000000"
    assert plan.filters["dock_doors_gte"] == 4
    assert plan.filters["requires_coordinates"] is True


def test_router_prefers_structured_plan_for_expanded_dataset_city_queries() -> None:
    plan = build_query_plan("Show industrial listings in Atlanta with map links")

    assert plan.route_mode == "instant"
    assert plan.query_type == "generic_property_search"
    assert "atlanta" in plan.filters["locations"]
    assert plan.filters["requires_coordinates"] is True


def test_router_expands_macro_region_queries_for_structured_search() -> None:
    plan = build_query_plan("Show industrial listings in Europe with map links")

    assert plan.route_mode == "instant"
    assert plan.query_type == "generic_property_search"
    assert "france" in plan.filters["locations"]
    assert "germany" in plan.filters["locations"]


def test_router_prefers_structured_plan_for_corpus_seed_locations() -> None:
    plan = build_query_plan("Show office listings in Toronto with map links")

    assert plan.route_mode == "instant"
    assert plan.query_type == "generic_property_search"
    assert "toronto" in plan.filters["locations"]
    assert plan.filters["requires_coordinates"] is True


def test_router_prefers_structured_plan_for_live_qdrant_locations(monkeypatch) -> None:
    monkeypatch.setattr(query_constructor, "_load_live_qdrant_location_values", lambda: {"lisbon", "portugal", "alfama"})

    plan = build_query_plan("Show office listings in Lisbon with map links")

    assert plan.route_mode == "instant"
    assert plan.query_type == "generic_property_search"
    assert "lisbon" in plan.filters["locations"]
    assert plan.filters["requires_coordinates"] is True
