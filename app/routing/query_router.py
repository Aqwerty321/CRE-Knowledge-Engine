from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from app.retrieval.alias_expansion import AliasExpander
from app.retrieval.retrieval_config import load_hybrid_retrieval_config
from app.routing.query_constructor import build_structured_query_spec

DEMO_ANCHORS: dict[str, tuple[float, float]] = {
    "123 main street": (40.7505, -73.9970),
    "123 main st": (40.7505, -73.9970),
}

LOADING_ACCESS_CONCEPT = "loading_access_or_yard_space"

SUPPORTED_QUERY_HINTS = [
    "near 123 Main Street",
    "office listings under a $/SF threshold",
    "structured filters such as industrial over 30k SF under $25/SF",
    "exact property lookup such as what do we know about 700 Logistics Pkwy",
    "data-quality questions such as what source data is missing",
    "tenant-fit shortlists such as best logistics options under $35/SF",
    "industrial square footage from John's files or notes",
    "source lookup for the $42/SF figure at 120 Main",
    "Harbor Rd change detection and rationale",
    "listings that mention loading access or yard space",
]


@dataclass(frozen=True)
class QueryPlan:
    route_mode: str
    query_type: str
    route_confidence: Decimal
    reason_codes: list[str]
    filters: dict[str, object]


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("?", " ").split())


def _normalize_address(address: str) -> str:
    return " ".join(address.lower().replace(",", " ").split())


def _extract_currency_threshold(query_text: str) -> Decimal | None:
    match = re.search(r"under\s+\$?(\d+(?:\.\d+)?)", query_text)
    return Decimal(match.group(1)) if match else None


def _loading_access_expanded_terms() -> list[str]:
    return list(load_hybrid_retrieval_config().concept_terms(LOADING_ACCESS_CONCEPT))


def _matches_loading_access_concept(query_text: str) -> bool:
    config = load_hybrid_retrieval_config()
    return AliasExpander(config).matches_concept(query_text, LOADING_ACCESS_CONCEPT)


def build_query_plan(query_text: str) -> QueryPlan:
    normalized = _normalize_text(query_text)

    for anchor_text, coordinates in DEMO_ANCHORS.items():
        if "near" in normalized and anchor_text in normalized:
            return QueryPlan(
                route_mode="instant",
                query_type="proximity",
                route_confidence=Decimal("0.9900"),
                reason_codes=["instant", "proximity", "anchor_address"],
                filters={
                    "anchor_address": "123 Main Street",
                    "anchor_lat": coordinates[0],
                    "anchor_lng": coordinates[1],
                    "limit": 3,
                },
            )

    threshold = _extract_currency_threshold(normalized)
    if threshold is not None and "office" in normalized:
        return QueryPlan(
            route_mode="instant",
            query_type="office_under_threshold",
            route_confidence=Decimal("0.9800"),
            reason_codes=["instant", "numeric_filter", "office_inventory"],
            filters={
                "property_type": "office",
                "price_per_sq_ft_lt": str(threshold),
            },
        )

    if "total square footage" in normalized and "industrial" in normalized and "john" in normalized:
        return QueryPlan(
            route_mode="instant",
            query_type="john_industrial_square_footage",
            route_confidence=Decimal("0.9600"),
            reason_codes=["instant", "aggregation", "source_owner"],
            filters={
                "property_type": "industrial",
                "slack_user_name": "John",
                "source_types": ["pdf", "text", "csv", "xlsx"],
                "dedupe_key": "duplicate_group_key",
            },
        )

    if "where did" in normalized and "120 main" in normalized:
        prefix = normalized.split("for 120 main", maxsplit=1)[0]
        matches = re.findall(r"\d+(?:\.\d+)?", prefix)
        if matches:
            return QueryPlan(
                route_mode="instant",
                query_type="source_lookup",
                route_confidence=Decimal("0.9700"),
                reason_codes=["instant", "source_lookup", "exact_field_match"],
                filters={
                    "address": "120 Main St",
                    "normalized_address": _normalize_address("120 Main St"),
                    "price_per_sq_ft": matches[-1],
                },
            )

    if ("why did you use" in normalized or "why use" in normalized) and "harbor" in normalized and (
        "62k" in normalized or "62000" in normalized or ("62" in normalized and "sq ft" in normalized)
    ):
        return QueryPlan(
            route_mode="hybrid",
            query_type="harbor_conflict_why",
            route_confidence=Decimal("0.9700"),
            reason_codes=["hybrid", "conflict_review", "freshness_priority"],
            filters={
                "address": "240 Harbor Rd",
                "duplicate_group_key": "240 harbor rd|industrial",
                "selected_sq_ft": 62000,
                "superseded_sq_ft": 58000,
                "retrieval_mode": "keyword_conflict_review",
            },
        )

    if ("change" in normalized or "updated" in normalized) and "harbor" in normalized:
        return QueryPlan(
            route_mode="hybrid",
            query_type="harbor_change_review",
            route_confidence=Decimal("0.9600"),
            reason_codes=["hybrid", "change_detection", "conflict_review"],
            filters={
                "address": "240 Harbor Rd",
                "duplicate_group_key": "240 harbor rd|industrial",
                "selected_sq_ft": 62000,
                "superseded_sq_ft": 58000,
                "retrieval_mode": "keyword_conflict_review",
            },
        )

    if _matches_loading_access_concept(query_text):
        return QueryPlan(
            route_mode="hybrid",
            query_type="loading_access_search",
            route_confidence=Decimal("0.9500"),
            reason_codes=["hybrid", "hybrid_local_retrieval", "chunk_keyword_search", "industrial_features"],
            filters={
                "property_type": "industrial",
                "concept": LOADING_ACCESS_CONCEPT,
                "expanded_terms": _loading_access_expanded_terms(),
                "query_text": query_text,
                "retrieval_mode": "hybrid_lexical_fuzzy",
            },
        )

    structured_spec = build_structured_query_spec(query_text)
    if structured_spec is not None:
        return QueryPlan(
            route_mode=structured_spec.route_mode,
            query_type=f"generic_{structured_spec.intent}",
            route_confidence=structured_spec.route_confidence,
            reason_codes=structured_spec.reason_codes,
            filters=structured_spec.to_filters(),
        )

    return QueryPlan(
        route_mode="failed",
        query_type="unsupported",
        route_confidence=Decimal("0.0000"),
        reason_codes=["unsupported_query"],
        filters={"supported_queries": SUPPORTED_QUERY_HINTS},
    )


__all__ = ["QueryPlan", "SUPPORTED_QUERY_HINTS", "build_query_plan"]