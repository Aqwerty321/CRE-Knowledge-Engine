from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


DEMO_REFERENCE_DATE = date(2026, 5, 17)

PROPERTY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "office": ("office", "offices", "office building", "office buildings"),
    "industrial": ("industrial", "warehouse", "warehouses", "distribution", "logistics", "flex", "yard"),
    "retail": ("retail", "storefront", "storefronts"),
    "mixed_use": ("mixed use", "mixed-use", "mixed_use"),
    "land": ("land", "site", "parcel"),
    "multifamily": ("multifamily", "multi family", "apartments", "residential"),
}

KNOWN_ADDRESS_ALIASES: dict[str, str] = {
    "120 main": "120 main st",
    "120 main st": "120 main st",
    "main street": "120 main st",
    "17 pine": "17 pine st",
    "17 pine st": "17 pine st",
    "pine st": "17 pine st",
    "900 north": "900 north loop",
    "north loop": "900 north loop",
    "130 elm": "130 elm ave",
    "elm ave": "130 elm ave",
    "455 market": "455 market st",
    "market st": "455 market st",
    "88 foundry": "88 foundry ln",
    "foundry": "88 foundry ln",
    "240 harbor": "240 harbor rd",
    "harbor rd": "240 harbor rd",
    "700 logistics": "700 logistics pkwy",
    "logistics pkwy": "700 logistics pkwy",
    "310 canal": "310 canal works",
    "canal works": "310 canal works",
    "64 union": "64 union yard",
    "union yard": "64 union yard",
    "18 beacon": "18 beacon freight",
    "beacon freight": "18 beacon freight",
    "42 spruce": "42 spruce flex",
    "spruce flex": "42 spruce flex",
    "510 river": "510 river cold storage",
    "river cold storage": "510 river cold storage",
    "75 orchard": "75 orchard office",
    "orchard office": "75 orchard office",
    "22 gallery": "22 gallery row",
    "gallery row": "22 gallery row",
    "600 skyline": "600 skyline office",
    "skyline office": "600 skyline office",
}

KNOWN_MARKETS = {
    "penn plaza",
    "west side",
    "market corridor",
    "downtown",
    "midtown",
    "harbor district",
    "logistics belt",
    "canal district",
    "main west",
}

KNOWN_UPLOADER_NAMES = {"john": "John", "sarah": "Sarah", "maya": "Maya", "priya": "Priya"}

SUBJECTIVE_TERMS = {
    "best",
    "promising",
    "recommend",
    "recommendation",
    "fit",
    "good fit",
    "shortlist",
    "client note",
    "memo",
}

LISTING_VERBS = {"show", "find", "list", "which", "what", "give", "pull"}
AGGREGATION_TERMS = {"total", "sum", "count", "how many", "average", "avg"}
MISSING_DATA_TERMS = {"missing", "unknown", "incomplete", "coverage", "data quality"}


@dataclass(frozen=True)
class StructuredQuerySpec:
    intent: str
    route_mode: str
    route_confidence: Decimal
    reason_codes: list[str]
    property_types: list[str] = field(default_factory=list)
    address_terms: list[str] = field(default_factory=list)
    uploader_names: list[str] = field(default_factory=list)
    markets: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    price_per_sq_ft_lt: Decimal | None = None
    price_per_sq_ft_gt: Decimal | None = None
    sq_ft_gte: int | None = None
    sq_ft_lte: int | None = None
    availability_before: date | None = None
    require_immediate: bool = False
    aggregate: str | None = None
    aggregate_field: str | None = None
    sort: str | None = None
    limit: int = 5
    missing_fields: list[str] = field(default_factory=list)
    tenant_profile: str | None = None

    def to_filters(self) -> dict[str, object]:
        return {
            "intent": self.intent,
            "property_types": self.property_types,
            "address_terms": self.address_terms,
            "uploader_names": self.uploader_names,
            "markets": self.markets,
            "keywords": self.keywords,
            "price_per_sq_ft_lt": str(self.price_per_sq_ft_lt) if self.price_per_sq_ft_lt is not None else None,
            "price_per_sq_ft_gt": str(self.price_per_sq_ft_gt) if self.price_per_sq_ft_gt is not None else None,
            "sq_ft_gte": self.sq_ft_gte,
            "sq_ft_lte": self.sq_ft_lte,
            "availability_before": self.availability_before.isoformat() if self.availability_before else None,
            "require_immediate": self.require_immediate,
            "aggregate": self.aggregate,
            "aggregate_field": self.aggregate_field,
            "sort": self.sort,
            "limit": self.limit,
            "missing_fields": self.missing_fields,
            "tenant_profile": self.tenant_profile,
        }


def _normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("?", " ").replace(",", " ").split())


def _has_phrase(normalized: str, phrases: set[str]) -> bool:
    return any(phrase in normalized for phrase in phrases)


def _extract_limit(normalized: str) -> int:
    match = re.search(r"\b(?:top|first|limit)\s+(\d{1,2})\b", normalized)
    if match:
        return max(1, min(10, int(match.group(1))))
    return 5


def _parse_compact_number(raw_value: str, suffix: str | None = None) -> int:
    cleaned = raw_value.replace(",", "")
    number = Decimal(cleaned)
    if suffix == "k":
        number *= Decimal("1000")
    return int(number)


def _is_upper_operator(operator: str) -> bool:
    return operator in {"over", "above", "more than", "at least", ">=", "min", "minimum"}


def _is_lower_operator(operator: str) -> bool:
    return operator in {"under", "below", "less than", "<=", "max", "maximum"}


def _extract_size_constraints(normalized: str) -> tuple[int | None, int | None, list[str]]:
    sq_ft_gte: int | None = None
    sq_ft_lte: int | None = None
    reason_codes: list[str] = []
    pattern = re.compile(
        r"\b(under|below|less than|<=|max|maximum|over|above|more than|at least|>=|min|minimum)\s+"
        r"(\d+(?:,\d{3})*(?:\.\d+)?)(k)?\s*(?:sf|sq\s*ft|sqft|square\s*feet)\b"
    )
    for match in pattern.finditer(normalized):
        operator, raw_value, suffix = match.groups()
        value = _parse_compact_number(raw_value, suffix)
        if _is_upper_operator(operator):
            sq_ft_gte = value
            reason_codes.append("sq_ft_lower_bound")
        elif _is_lower_operator(operator):
            sq_ft_lte = value
            reason_codes.append("sq_ft_upper_bound")
    return sq_ft_gte, sq_ft_lte, reason_codes


def _extract_price_constraints(query_text: str) -> tuple[Decimal | None, Decimal | None, list[str]]:
    normalized = _normalize_text(query_text)
    price_lt: Decimal | None = None
    price_gt: Decimal | None = None
    reason_codes: list[str] = []
    pattern = re.compile(
        r"\b(under|below|less than|<=|max|maximum|over|above|more than|at least|>=|min|minimum)\s+"
        r"(\$)?(\d+(?:\.\d+)?)\s*(?:/\s*sf|per\s*sf|psf|/\s*sq\s*ft|sq\s*ft)?\b"
    )
    for match in pattern.finditer(normalized):
        operator, dollar, raw_value = match.groups()
        window = normalized[max(0, match.start() - 18) : min(len(normalized), match.end() + 24)]
        if not dollar and not any(term in window for term in ("/sf", "per sf", "psf", "rent", "price", "asking", "$")):
            continue

        value = Decimal(raw_value)
        if _is_upper_operator(operator):
            price_gt = value
            reason_codes.append("price_lower_bound")
        elif _is_lower_operator(operator):
            price_lt = value
            reason_codes.append("price_upper_bound")
    return price_lt, price_gt, reason_codes


def _extract_property_types(normalized: str) -> tuple[list[str], list[str]]:
    matches: list[str] = []
    reason_codes: list[str] = []
    for property_type, aliases in PROPERTY_TYPE_ALIASES.items():
        if any(alias in normalized for alias in aliases):
            matches.append(property_type)
            reason_codes.append("property_type_detected")
    return sorted(set(matches)), sorted(set(reason_codes))


def _extract_address_terms(normalized: str) -> tuple[list[str], list[str]]:
    matches = [normalized_address for alias, normalized_address in KNOWN_ADDRESS_ALIASES.items() if alias in normalized]
    reason_codes = ["address_detected"] if matches else []
    return sorted(set(matches)), reason_codes


def _extract_markets(normalized: str) -> tuple[list[str], list[str]]:
    matches = [market for market in KNOWN_MARKETS if market in normalized]
    reason_codes = ["market_detected"] if matches else []
    return sorted(matches), reason_codes


def _extract_uploaders(normalized: str) -> tuple[list[str], list[str]]:
    matches = [display_name for name, display_name in KNOWN_UPLOADER_NAMES.items() if name in normalized]
    reason_codes = ["source_owner"] if matches else []
    return sorted(set(matches)), reason_codes


def _extract_keywords(normalized: str) -> list[str]:
    keyword_map = {
        "loading": "loading dock",
        "dock": "loading dock",
        "yard": "yard",
        "trailer": "trailer",
        "logistics": "logistics",
        "correction": "correction",
        "market snapshot": "market snapshot",
        "tenant": "tenant",
        "sublease": "sublease",
        "truck court": "truck court",
        "cold storage": "cold storage",
        "grade-level": "grade-level door",
        "grade level": "grade-level door",
    }
    return sorted({term for marker, term in keyword_map.items() if marker in normalized})


def _extract_availability(normalized: str) -> tuple[date | None, bool, list[str]]:
    if "immediate" in normalized or "available now" in normalized or "vacant" in normalized or re.search(r"\bnow\b", normalized):
        return DEMO_REFERENCE_DATE, True, ["availability_immediate"]
    if any(term in normalized for term in ("soon", "near term", "near-term", "next quarter")):
        return date(2026, 8, 31), False, ["availability_window"]
    if "q2 2026" in normalized:
        return date(2026, 6, 30), False, ["availability_window"]
    if "q3 2026" in normalized:
        return date(2026, 9, 30), False, ["availability_window"]
    if "q4 2026" in normalized:
        return date(2026, 12, 31), False, ["availability_window"]
    return None, False, []


def _extract_missing_fields(normalized: str) -> list[str]:
    field_aliases = {
        "sq_ft": ("square footage", "sq ft", "sqft", "size"),
        "price_per_sq_ft": ("price", "rent", "$/sf", "psf", "rate"),
        "availability": ("availability", "available"),
        "market": ("market", "submarket"),
        "geo": ("coordinate", "coordinates", "lat", "lng", "location"),
        "source_url": ("link", "url", "permalink"),
    }
    matches = [field_name for field_name, aliases in field_aliases.items() if any(alias in normalized for alias in aliases)]
    return matches or ["sq_ft", "price_per_sq_ft", "availability", "market", "geo", "source_url"]


def _extract_aggregation(normalized: str) -> tuple[str | None, str | None, list[str]]:
    if "how many" in normalized or "count" in normalized:
        return "count", "property_records", ["aggregation"]
    if "average" in normalized or "avg" in normalized:
        if any(term in normalized for term in ("price", "rent", "$/sf", "psf")):
            return "average", "price_per_sq_ft", ["aggregation", "numeric_field"]
        return "average", "sq_ft", ["aggregation", "numeric_field"]
    if "total" in normalized or "sum" in normalized:
        return "total", "sq_ft", ["aggregation", "numeric_field"]
    return None, None, []


def build_structured_query_spec(query_text: str) -> StructuredQuerySpec | None:
    normalized = _normalize_text(query_text)
    if not normalized:
        return None

    reason_codes: list[str] = ["heuristic_router"]
    property_types, codes = _extract_property_types(normalized)
    reason_codes.extend(codes)
    address_terms, codes = _extract_address_terms(normalized)
    reason_codes.extend(codes)
    uploader_names, codes = _extract_uploaders(normalized)
    reason_codes.extend(codes)
    markets, codes = _extract_markets(normalized)
    reason_codes.extend(codes)
    keywords = _extract_keywords(normalized)
    if keywords:
        reason_codes.append("keyword_terms")

    price_lt, price_gt, codes = _extract_price_constraints(query_text)
    reason_codes.extend(codes)
    sq_ft_gte, sq_ft_lte, codes = _extract_size_constraints(normalized)
    reason_codes.extend(codes)
    availability_before, require_immediate, codes = _extract_availability(normalized)
    reason_codes.extend(codes)
    aggregate, aggregate_field, codes = _extract_aggregation(normalized)
    reason_codes.extend(codes)
    limit = _extract_limit(normalized)

    if any(term in normalized for term in MISSING_DATA_TERMS):
        return StructuredQuerySpec(
            intent="data_completeness",
            route_mode="instant",
            route_confidence=Decimal("0.9300"),
            reason_codes=sorted(set([*reason_codes, "missing_data_review"])),
            property_types=property_types,
            address_terms=address_terms,
            uploader_names=uploader_names,
            markets=markets,
            missing_fields=_extract_missing_fields(normalized),
            limit=limit,
        )

    subjective = _has_phrase(normalized, SUBJECTIVE_TERMS)
    tenant_profile = "logistics" if "logistics" in normalized and ("tenant" in normalized or subjective) else None
    if subjective or tenant_profile:
        if tenant_profile == "logistics" and "industrial" not in property_types:
            property_types = [*property_types, "industrial"]
        tenant_keywords = (
            sorted(set([*keywords, "loading dock", "dock doors", "yard", "truck court", "trailer parking", "logistics"]))
            if tenant_profile
            else keywords
        )
        return StructuredQuerySpec(
            intent="tenant_fit",
            route_mode="hybrid",
            route_confidence=Decimal("0.8700"),
            reason_codes=sorted(set([*reason_codes, "local_synthesis", "subjective_intent"])),
            property_types=sorted(set(property_types)),
            address_terms=address_terms,
            uploader_names=uploader_names,
            markets=markets,
            keywords=tenant_keywords,
            price_per_sq_ft_lt=price_lt,
            price_per_sq_ft_gt=price_gt,
            sq_ft_gte=sq_ft_gte,
            sq_ft_lte=sq_ft_lte,
            availability_before=availability_before,
            require_immediate=require_immediate,
            sort="tenant_fit",
            limit=limit,
            tenant_profile=tenant_profile,
        )

    if aggregate is not None:
        return StructuredQuerySpec(
            intent="aggregation",
            route_mode="instant",
            route_confidence=Decimal("0.9200"),
            reason_codes=sorted(set(reason_codes)),
            property_types=property_types,
            address_terms=address_terms,
            uploader_names=uploader_names,
            markets=markets,
            keywords=keywords,
            price_per_sq_ft_lt=price_lt,
            price_per_sq_ft_gt=price_gt,
            sq_ft_gte=sq_ft_gte,
            sq_ft_lte=sq_ft_lte,
            availability_before=availability_before,
            require_immediate=require_immediate,
            aggregate=aggregate,
            aggregate_field=aggregate_field,
            limit=limit,
        )

    sort: str | None = None
    if any(term in normalized for term in ("cheapest", "lowest rent", "lowest price")):
        sort = "price_asc"
        reason_codes.append("sort_price")
    elif any(term in normalized for term in ("largest", "biggest", "most square")):
        sort = "size_desc"
        reason_codes.append("sort_size")
    elif any(term in normalized for term in ("soonest", "earliest", "available first")):
        sort = "availability_asc"
        reason_codes.append("sort_availability")

    has_structured_signal = bool(
        property_types
        or address_terms
        or uploader_names
        or markets
        or keywords
        or price_lt is not None
        or price_gt is not None
        or sq_ft_gte is not None
        or sq_ft_lte is not None
        or availability_before is not None
    )
    asks_for_listing = any(normalized.startswith(verb) or f" {verb} " in f" {normalized} " for verb in LISTING_VERBS)

    if address_terms and any(term in normalized for term in ("know about", "details", "detail", "tell me about")):
        intent = "exact_lookup"
        confidence = Decimal("0.9400")
        reason_codes.append("exact_lookup")
    elif has_structured_signal and (asks_for_listing or property_types or price_lt is not None or sq_ft_gte is not None):
        intent = "property_search"
        confidence = Decimal("0.9000")
        reason_codes.append("structured_property_search")
    else:
        return None

    return StructuredQuerySpec(
        intent=intent,
        route_mode="instant",
        route_confidence=confidence,
        reason_codes=sorted(set(reason_codes)),
        property_types=property_types,
        address_terms=address_terms,
        uploader_names=uploader_names,
        markets=markets,
        keywords=keywords,
        price_per_sq_ft_lt=price_lt,
        price_per_sq_ft_gt=price_gt,
        sq_ft_gte=sq_ft_gte,
        sq_ft_lte=sq_ft_lte,
        availability_before=availability_before,
        require_immediate=require_immediate,
        sort=sort,
        limit=limit,
    )


__all__ = ["DEMO_REFERENCE_DATE", "StructuredQuerySpec", "build_structured_query_spec"]
