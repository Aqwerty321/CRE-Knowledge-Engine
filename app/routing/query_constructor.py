from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import get_settings
from app.db.session import SessionFactory
from app.ingestion.large_corpus_builder import EUROPE_MARKETS, GLOBAL_CONTROL_MARKETS, US_MARKETS
from app.models import PropertyRecord
from sqlalchemy import select


DEMO_REFERENCE_DATE = date(2026, 5, 17)

PROPERTY_TYPE_ALIASES: dict[str, tuple[str, ...]] = {
    "office": ("office", "offices", "office building", "office buildings"),
    "industrial": ("industrial", "warehouse", "warehouses", "distribution", "logistics", "flex", "yard"),
    "retail": ("retail", "storefront", "storefronts"),
    "mixed_use": ("mixed use", "mixed-use", "mixed_use"),
    "land": ("land", "site", "parcel"),
    "multifamily": ("multifamily", "multi family", "apartments", "residential"),
    "hospitality": ("hospitality", "hotel", "hotels", "motel", "lodging"),
    "medical": ("medical", "clinic", "healthcare", "health care", "medical office"),
    "life_science": ("life science", "life-science", "lab", "laboratory", "biotech"),
    "data_center": ("data center", "data centre", "colo", "colocation"),
    "self_storage": ("self storage", "self-storage", "storage units"),
    "parking": ("parking", "garage", "surface lot", "car park"),
    "student_housing": ("student housing", "student apartments"),
    "senior_housing": ("senior housing", "assisted living"),
    "cold_storage": ("cold storage", "refrigerated warehouse", "freezer"),
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
    "brooklyn",
    "queens",
    "inland empire",
    "south bay",
    "soho",
    "shoreditch",
    "la defense",
    "kreuzberg",
    "amsterdam zuid",
    "22@",
    "zona tortona",
}

MANUAL_LOCATION_ALIASES: dict[str, tuple[str, ...]] = {
    "new york": ("nyc",),
    "united states": ("usa", "u.s.a."),
    "united kingdom": ("uk",),
    "dallas-fort worth": ("dfw", "fort worth"),
    "san francisco bay area": ("bay area",),
}

QDRANT_LOCATION_PAYLOAD_FIELDS = (
    "markets",
    "countries",
    "country_codes",
    "regions",
    "state_provinces",
    "cities",
    "localities",
    "neighborhoods",
    "submarkets",
)
LOCATION_LEXICON_CACHE_TTL_SECONDS = 60.0
_live_location_value_cache: tuple[float, frozenset[str]] | None = None
_property_record_location_value_cache: tuple[float, frozenset[str]] | None = None

MACRO_LOCATION_ALIASES: dict[str, tuple[str, ...]] = {
    "europe": (
        "france",
        "germany",
        "spain",
        "netherlands",
        "ireland",
        "sweden",
        "denmark",
        "united kingdom",
    ),
    "european": (
        "france",
        "germany",
        "spain",
        "netherlands",
        "ireland",
        "sweden",
        "denmark",
        "united kingdom",
    ),
}

STATUS_ALIASES: dict[str, tuple[str, ...]] = {
    "available": ("available", "active", "on market"),
    "coming_soon": ("coming soon", "pipeline", "soon", "future availability"),
    "under_offer": ("under offer", "loi", "letter of intent", "in negotiation"),
    "leased": ("leased", "let"),
    "sold": ("sold", "closed sale"),
    "withdrawn": ("withdrawn", "off market"),
    "pipeline": ("pipeline", "planned", "proposed"),
}

FURNISHING_ALIASES: dict[str, tuple[str, ...]] = {
    "furnished": ("furnished", "fully furnished"),
    "partially_furnished": ("partially furnished", "part furnished", "semi furnished"),
    "unfurnished": ("unfurnished", "not furnished"),
    "shell": ("shell", "cold shell"),
    "warm_shell": ("warm shell", "white box", "white-box"),
    "turnkey": ("turnkey", "plug and play", "plug-and-play"),
}

FACING_ALIASES: dict[str, tuple[str, ...]] = {
    "north": ("north facing", "north-facing", "facing north"),
    "south": ("south facing", "south-facing", "facing south"),
    "east": ("east facing", "east-facing", "facing east"),
    "west": ("west facing", "west-facing", "facing west"),
    "corner": ("corner", "corner frontage"),
    "dual_aspect": ("dual aspect", "dual-aspect", "two sides"),
}

USAGE_ALIASES: dict[str, tuple[str, ...]] = {
    "office": ("office use", "workplace", "hq", "headquarters"),
    "logistics": ("logistics", "last mile", "last-mile", "distribution", "fulfillment"),
    "retail": ("retail use", "restaurant", "showroom", "storefront"),
    "medical": ("medical use", "clinic", "healthcare", "health care"),
    "residential": ("residential", "apartments", "housing"),
    "hospitality": ("hospitality", "hotel", "lodging"),
    "data_center": ("data center", "data centre", "colocation"),
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
INVENTORY_NOUNS = {
    "availabilities",
    "availability",
    "buildings",
    "deals",
    "inventory",
    "listings",
    "options",
    "opportunities",
    "properties",
    "property",
    "sites",
    "spaces",
}
INVENTORY_PHRASES = {
    "all listings",
    "all options",
    "all properties",
    "available options",
    "current inventory",
    "in our database",
    "in the database",
    "list all",
    "show all",
    "show me all",
    "what do we have",
    "what is available",
    "what listings",
    "what options",
    "what properties",
    "what's available",
}


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
    locations: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)
    usage_types: list[str] = field(default_factory=list)
    facing: list[str] = field(default_factory=list)
    furnishing_statuses: list[str] = field(default_factory=list)
    infrastructure_terms: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    price_per_sq_ft_lt: Decimal | None = None
    price_per_sq_ft_gt: Decimal | None = None
    sale_price_lt: Decimal | None = None
    sale_price_gt: Decimal | None = None
    cap_rate_gte: Decimal | None = None
    cap_rate_lte: Decimal | None = None
    sq_ft_gte: int | None = None
    sq_ft_lte: int | None = None
    clear_height_ft_gte: Decimal | None = None
    dock_doors_gte: int | None = None
    trailer_parking_spaces_gte: int | None = None
    parking_spaces_gte: int | None = None
    availability_before: date | None = None
    require_immediate: bool = False
    requires_coordinates: bool = False
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
            "locations": self.locations,
            "statuses": self.statuses,
            "usage_types": self.usage_types,
            "facing": self.facing,
            "furnishing_statuses": self.furnishing_statuses,
            "infrastructure_terms": self.infrastructure_terms,
            "keywords": self.keywords,
            "price_per_sq_ft_lt": str(self.price_per_sq_ft_lt) if self.price_per_sq_ft_lt is not None else None,
            "price_per_sq_ft_gt": str(self.price_per_sq_ft_gt) if self.price_per_sq_ft_gt is not None else None,
            "sale_price_lt": str(self.sale_price_lt) if self.sale_price_lt is not None else None,
            "sale_price_gt": str(self.sale_price_gt) if self.sale_price_gt is not None else None,
            "cap_rate_gte": str(self.cap_rate_gte) if self.cap_rate_gte is not None else None,
            "cap_rate_lte": str(self.cap_rate_lte) if self.cap_rate_lte is not None else None,
            "sq_ft_gte": self.sq_ft_gte,
            "sq_ft_lte": self.sq_ft_lte,
            "clear_height_ft_gte": str(self.clear_height_ft_gte) if self.clear_height_ft_gte is not None else None,
            "dock_doors_gte": self.dock_doors_gte,
            "trailer_parking_spaces_gte": self.trailer_parking_spaces_gte,
            "parking_spaces_gte": self.parking_spaces_gte,
            "availability_before": self.availability_before.isoformat() if self.availability_before else None,
            "require_immediate": self.require_immediate,
            "requires_coordinates": self.requires_coordinates,
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
    return any(_contains_alias(normalized, phrase) for phrase in phrases)


def _contains_alias(normalized: str, alias: str) -> bool:
    escaped = re.escape(alias.lower().strip())
    return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", normalized) is not None


def _normalize_location_value(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _is_high_signal_location_value(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    if re.fullmatch(r"[A-Z]{2,3}", stripped):
        return False
    normalized = _normalize_location_value(stripped)
    return len(normalized) >= 3 or any(character.isdigit() for character in normalized)


def _location_alias_variants(value: str) -> set[str]:
    canonical = _normalize_location_value(value)
    variants = {canonical}

    punctuation_spaced = _normalize_text(re.sub(r"[^a-z0-9]+", " ", canonical))
    if punctuation_spaced:
        variants.add(punctuation_spaced)

    if "/" in canonical:
        variants.add(_normalize_text(canonical.replace("/", " ")))
        for part in canonical.split("/"):
            normalized_part = _normalize_location_value(part)
            if normalized_part:
                variants.add(normalized_part)

    if "-" in canonical:
        variants.add(_normalize_text(canonical.replace("-", " ")))

    return {variant for variant in variants if variant}


def _register_location_value(alias_map: dict[str, set[str]], canonical_value: str, *aliases: str) -> None:
    if not _is_high_signal_location_value(canonical_value):
        return

    canonical = _normalize_location_value(canonical_value)
    alias_map.setdefault(canonical, set()).update(_location_alias_variants(canonical_value))
    for alias in aliases:
        alias_map[canonical].update(_location_alias_variants(alias))


@lru_cache(maxsize=1)
def _build_seed_location_aliases() -> dict[str, tuple[str, ...]]:
    alias_map: dict[str, set[str]] = {}

    for market_seed in (*US_MARKETS, *EUROPE_MARKETS, *GLOBAL_CONTROL_MARKETS):
        _register_location_value(alias_map, market_seed.market)
        _register_location_value(alias_map, market_seed.city)
        _register_location_value(alias_map, market_seed.country)
        _register_location_value(alias_map, market_seed.state_province)
        for neighborhood in market_seed.neighborhoods:
            _register_location_value(alias_map, neighborhood)
            _register_location_value(alias_map, f"{market_seed.market} - {neighborhood}")

    for canonical, aliases in MANUAL_LOCATION_ALIASES.items():
        _register_location_value(alias_map, canonical, *aliases)

    return {canonical: tuple(sorted(aliases)) for canonical, aliases in alias_map.items()}


def _fetch_live_qdrant_location_values() -> set[str]:
    settings = get_settings()
    if not settings.qdrant_url or not (settings.vector_search_enabled or settings.vector_index_on_import):
        return set()

    url = f"{settings.qdrant_url.rstrip('/')}/collections/{settings.qdrant_collection}/points/scroll"
    offset: object | None = None
    values: set[str] = set()

    for _ in range(32):
        payload: dict[str, object] = {
            "limit": 256,
            "with_payload": list(QDRANT_LOCATION_PAYLOAD_FIELDS),
            "with_vector": False,
        }
        if offset is not None:
            payload["offset"] = offset

        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=1.5) as response:
                body = json.load(response)
        except (HTTPError, URLError, OSError, TimeoutError, ValueError, json.JSONDecodeError):
            return set()

        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict):
            break

        points = result.get("points")
        if not isinstance(points, list) or not points:
            break

        for point in points:
            payload_row = point.get("payload") if isinstance(point, dict) else None
            if not isinstance(payload_row, dict):
                continue
            for field_name in QDRANT_LOCATION_PAYLOAD_FIELDS:
                field_value = payload_row.get(field_name)
                if isinstance(field_value, str):
                    values.add(field_value)
                elif isinstance(field_value, list):
                    values.update(item for item in field_value if isinstance(item, str))

        next_offset = result.get("next_page_offset")
        if next_offset is None:
            break
        offset = next_offset

    return values


def _load_live_qdrant_location_values() -> set[str]:
    global _live_location_value_cache

    now = time.monotonic()
    if _live_location_value_cache is not None:
        expires_at, cached_values = _live_location_value_cache
        if now < expires_at:
            return set(cached_values)

    values = frozenset(_fetch_live_qdrant_location_values())
    _live_location_value_cache = (now + LOCATION_LEXICON_CACHE_TTL_SECONDS, values)
    return set(values)


def _property_record_location_snapshot_path() -> Path:
    return Path(".runtime/property-record-location-lexicon.json")


def _load_property_record_location_values() -> set[str]:
    global _property_record_location_value_cache

    now = time.monotonic()
    if _property_record_location_value_cache is not None:
        expires_at, cached_values = _property_record_location_value_cache
        if now < expires_at:
            return set(cached_values)

    snapshot_path = _property_record_location_snapshot_path()
    values: set[str] = set()
    try:
        payload = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError):
        payload = None

    field_values = payload.get("field_values") if isinstance(payload, dict) else None
    if isinstance(field_values, dict):
        for field_name in QDRANT_LOCATION_PAYLOAD_FIELDS:
            field_value = field_values.get(field_name)
            if isinstance(field_value, str):
                values.add(field_value)
            elif isinstance(field_value, list):
                values.update(item for item in field_value if isinstance(item, str))

    frozen_values = frozenset(values)
    _property_record_location_value_cache = (now + LOCATION_LEXICON_CACHE_TTL_SECONDS, frozen_values)
    return set(frozen_values)


async def refresh_property_record_location_snapshot() -> dict[str, object]:
    field_names = tuple(QDRANT_LOCATION_PAYLOAD_FIELDS)
    field_values: dict[str, set[str]] = {field_name: set() for field_name in field_names}

    async with SessionFactory() as session:
        rows = list(
            (
                await session.execute(
                    select(
                        PropertyRecord.market,
                        PropertyRecord.country,
                        PropertyRecord.country_code,
                        PropertyRecord.region,
                        PropertyRecord.state_province,
                        PropertyRecord.city,
                        PropertyRecord.locality,
                        PropertyRecord.neighborhood,
                        PropertyRecord.submarket,
                    )
                )
            ).all()
        )

    for row in rows:
        for field_name, value in zip(field_names, row, strict=False):
            if isinstance(value, str) and value.strip():
                field_values[field_name].add(value.strip())

    snapshot = {
        "updated_at": time.time(),
        "field_values": {field_name: sorted(values) for field_name, values in field_values.items()},
        "value_count": sum(len(values) for values in field_values.values()),
    }
    snapshot_path = _property_record_location_snapshot_path()
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(json.dumps(snapshot, indent=2, sort_keys=True), encoding="utf-8")
    invalidate_live_location_value_cache()
    return snapshot


def invalidate_live_location_value_cache() -> None:
    global _live_location_value_cache
    global _property_record_location_value_cache
    _live_location_value_cache = None
    _property_record_location_value_cache = None


def _build_known_location_aliases() -> dict[str, tuple[str, ...]]:
    alias_map = {canonical: set(aliases) for canonical, aliases in _build_seed_location_aliases().items()}
    for property_record_location_value in _load_property_record_location_values():
        _register_location_value(alias_map, property_record_location_value)
    for live_location_value in _load_live_qdrant_location_values():
        _register_location_value(alias_map, live_location_value)
    return {canonical: tuple(sorted(aliases)) for canonical, aliases in alias_map.items()}


def _extract_limit(normalized: str) -> int:
    match = re.search(r"\b(?:top|first|limit)\s+(\d{1,2})\b", normalized)
    if match:
        return max(1, min(10, int(match.group(1))))
    return 5


def _asks_for_listing(normalized: str) -> bool:
    return any(normalized.startswith(verb) or f" {verb} " in f" {normalized} " for verb in LISTING_VERBS)


def _asks_for_inventory(normalized: str) -> bool:
    if any(phrase in normalized for phrase in INVENTORY_PHRASES):
        return True
    if not any(noun in normalized for noun in INVENTORY_NOUNS):
        return False
    return _asks_for_listing(normalized) or any(term in normalized for term in ("all", "any", "available", "have"))


def _inventory_limit(normalized: str, requested_limit: int) -> int:
    if any(term in normalized for term in ("all", "inventory", "database", "what do we have")):
        return max(requested_limit, 25)
    return max(requested_limit, 10)


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


def _money_to_decimal(raw_value: str, suffix: str | None) -> Decimal:
    value = Decimal(raw_value.replace(",", ""))
    normalized_suffix = (suffix or "").lower()
    if normalized_suffix in {"m", "mm", "million"}:
        value *= Decimal("1000000")
    elif normalized_suffix in {"k", "thousand"}:
        value *= Decimal("1000")
    return value


def _extract_sale_price_constraints(normalized: str) -> tuple[Decimal | None, Decimal | None, list[str]]:
    sale_price_lt: Decimal | None = None
    sale_price_gt: Decimal | None = None
    reason_codes: list[str] = []
    pattern = re.compile(
        r"\b(under|below|less than|<=|max|maximum|over|above|more than|at least|>=|min|minimum)\s+"
        r"\$?(\d+(?:,\d{3})*(?:\.\d+)?)\s*(m|mm|million|k|thousand)?\b"
    )
    for match in pattern.finditer(normalized):
        window = normalized[max(0, match.start() - 28) : min(len(normalized), match.end() + 36)]
        if any(term in window for term in ("/sf", "per sf", "psf", "rent")):
            continue
        if not any(term in window for term in ("sale", "buy", "purchase", "acquisition", "asking price", "price")):
            continue

        operator, raw_value, suffix = match.groups()
        value = _money_to_decimal(raw_value, suffix)
        if _is_upper_operator(operator):
            sale_price_gt = value
            reason_codes.append("sale_price_lower_bound")
        elif _is_lower_operator(operator):
            sale_price_lt = value
            reason_codes.append("sale_price_upper_bound")
    return sale_price_lt, sale_price_gt, reason_codes


def _extract_cap_rate_constraints(normalized: str) -> tuple[Decimal | None, Decimal | None, list[str]]:
    cap_rate_gte: Decimal | None = None
    cap_rate_lte: Decimal | None = None
    reason_codes: list[str] = []
    pattern = re.compile(
        r"\b(?:cap\s*rate|capitalization\s*rate)\s*"
        r"(under|below|less than|<=|max|maximum|over|above|more than|at least|>=|min|minimum)?\s*"
        r"(\d+(?:\.\d+)?)\s*%?"
    )
    for match in pattern.finditer(normalized):
        operator, raw_value = match.groups()
        value = Decimal(raw_value) / Decimal("100")
        if operator is None or _is_upper_operator(operator):
            cap_rate_gte = value
            reason_codes.append("cap_rate_lower_bound")
        elif _is_lower_operator(operator):
            cap_rate_lte = value
            reason_codes.append("cap_rate_upper_bound")
    return cap_rate_gte, cap_rate_lte, reason_codes


def _extract_physical_constraints(normalized: str) -> tuple[Decimal | None, int | None, int | None, int | None, list[str]]:
    clear_height_ft_gte: Decimal | None = None
    dock_doors_gte: int | None = None
    trailer_parking_spaces_gte: int | None = None
    parking_spaces_gte: int | None = None
    reason_codes: list[str] = []

    clear_height_match = re.search(
        r"\b(?:clear\s*height|clearance)\s*(?:over|above|more than|at least|>=|min|minimum)?\s*(\d+(?:\.\d+)?)\s*(?:ft|feet)?\b",
        normalized,
    )
    if clear_height_match:
        clear_height_ft_gte = Decimal(clear_height_match.group(1))
        reason_codes.append("clear_height_lower_bound")

    dock_match = re.search(r"\b(?:at least|min|minimum|over|above|more than)?\s*(\d{1,3})\s*(?:dock doors?|dock-high doors?|loading doors?)\b", normalized)
    if dock_match:
        dock_doors_gte = int(dock_match.group(1))
        reason_codes.append("dock_doors_lower_bound")

    trailer_match = re.search(r"\b(?:at least|min|minimum|over|above|more than)?\s*(\d{1,4})\s*(?:trailer parking|trailer spaces?|trailer stalls?)\b", normalized)
    if trailer_match:
        trailer_parking_spaces_gte = int(trailer_match.group(1))
        reason_codes.append("trailer_parking_lower_bound")

    parking_match = re.search(r"\b(?:at least|min|minimum|over|above|more than)?\s*(\d{1,4})\s*(?:parking spaces?|car spaces?|stalls?)\b", normalized)
    if parking_match:
        parking_spaces_gte = int(parking_match.group(1))
        reason_codes.append("parking_spaces_lower_bound")

    return clear_height_ft_gte, dock_doors_gte, trailer_parking_spaces_gte, parking_spaces_gte, reason_codes


def _asks_for_coordinates(normalized: str) -> bool:
    return any(
        _contains_alias(normalized, term)
        for term in (
            "map",
            "maps",
            "map link",
            "coordinates",
            "coordinate",
            "geolocation",
            "geo location",
            "where is",
            "locate",
            "location link",
        )
    )


def _extract_property_types(normalized: str) -> tuple[list[str], list[str]]:
    matches: list[str] = []
    reason_codes: list[str] = []
    for property_type, aliases in PROPERTY_TYPE_ALIASES.items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            matches.append(property_type)
            reason_codes.append("property_type_detected")
    return sorted(set(matches)), sorted(set(reason_codes))


def _extract_address_terms(normalized: str) -> tuple[list[str], list[str]]:
    matches = [normalized_address for alias, normalized_address in KNOWN_ADDRESS_ALIASES.items() if _contains_alias(normalized, alias)]
    reason_codes = ["address_detected"] if matches else []
    return sorted(set(matches)), reason_codes


def _extract_markets(normalized: str) -> tuple[list[str], list[str]]:
    matches = [market for market in KNOWN_MARKETS if _contains_alias(normalized, market)]
    reason_codes = ["market_detected"] if matches else []
    return sorted(matches), reason_codes


def _extract_locations(normalized: str) -> tuple[list[str], list[str]]:
    matches: list[str] = []
    for location, aliases in _build_known_location_aliases().items():
        if any(_contains_alias(normalized, alias) for alias in aliases):
            matches.append(location)
    for alias, bundle in MACRO_LOCATION_ALIASES.items():
        if _contains_alias(normalized, alias):
            matches.extend(bundle)
    reason_codes = ["location_detected"] if matches else []
    return sorted(set(matches)), reason_codes


def _extract_alias_values(normalized: str, aliases_by_value: dict[str, tuple[str, ...]], reason_code: str) -> tuple[list[str], list[str]]:
    matches = [value for value, aliases in aliases_by_value.items() if any(_contains_alias(normalized, alias) for alias in aliases)]
    return sorted(set(matches)), [reason_code] if matches else []


def _extract_uploaders(normalized: str) -> tuple[list[str], list[str]]:
    matches = [display_name for name, display_name in KNOWN_UPLOADER_NAMES.items() if _contains_alias(normalized, name)]
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
        "map": "map",
        "maps": "map",
        "coordinate": "coordinates",
        "coordinates": "coordinates",
        "highway": "highway",
        "airport": "airport",
        "port": "port",
        "rail": "rail",
        "ev charging": "ev charging",
        "fiber": "fiber",
        "sprinkler": "sprinklered",
    }
    return sorted({term for marker, term in keyword_map.items() if _contains_alias(normalized, marker)})


def _extract_infrastructure_terms(normalized: str, keywords: list[str]) -> tuple[list[str], list[str]]:
    terms = [
        keyword
        for keyword in keywords
        if keyword in {"loading dock", "yard", "trailer", "truck court", "cold storage", "grade-level door", "highway", "airport", "port", "rail", "ev charging", "fiber", "sprinklered"}
    ]
    return sorted(set(terms)), ["infrastructure_terms"] if terms else []


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
    locations, codes = _extract_locations(normalized)
    reason_codes.extend(codes)
    statuses, codes = _extract_alias_values(normalized, STATUS_ALIASES, "status_detected")
    reason_codes.extend(codes)
    usage_types, codes = _extract_alias_values(normalized, USAGE_ALIASES, "usage_detected")
    reason_codes.extend(codes)
    facing, codes = _extract_alias_values(normalized, FACING_ALIASES, "facing_detected")
    reason_codes.extend(codes)
    furnishing_statuses, codes = _extract_alias_values(normalized, FURNISHING_ALIASES, "furnishing_detected")
    reason_codes.extend(codes)
    keywords = _extract_keywords(normalized)
    if keywords:
        reason_codes.append("keyword_terms")
    infrastructure_terms, codes = _extract_infrastructure_terms(normalized, keywords)
    reason_codes.extend(codes)

    price_lt, price_gt, codes = _extract_price_constraints(query_text)
    reason_codes.extend(codes)
    sale_price_lt, sale_price_gt, codes = _extract_sale_price_constraints(normalized)
    reason_codes.extend(codes)
    cap_rate_gte, cap_rate_lte, codes = _extract_cap_rate_constraints(normalized)
    reason_codes.extend(codes)
    sq_ft_gte, sq_ft_lte, codes = _extract_size_constraints(normalized)
    reason_codes.extend(codes)
    clear_height_ft_gte, dock_doors_gte, trailer_parking_spaces_gte, parking_spaces_gte, codes = _extract_physical_constraints(normalized)
    reason_codes.extend(codes)
    availability_before, require_immediate, codes = _extract_availability(normalized)
    reason_codes.extend(codes)
    aggregate, aggregate_field, codes = _extract_aggregation(normalized)
    reason_codes.extend(codes)

    if dock_doors_gte is not None:
        keywords = [keyword for keyword in keywords if keyword != "loading dock"]
        infrastructure_terms = [term for term in infrastructure_terms if term != "loading dock"]
    if trailer_parking_spaces_gte is not None:
        keywords = [keyword for keyword in keywords if keyword != "trailer"]
        infrastructure_terms = [term for term in infrastructure_terms if term != "trailer"]

    locations = sorted(set([*locations, *markets]))

    requires_coordinates = _asks_for_coordinates(normalized)
    if requires_coordinates:
        keywords = [keyword for keyword in keywords if keyword not in {"map", "coordinates"}]
        reason_codes.append("geo_lookup")
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
            locations=locations,
            statuses=statuses,
            usage_types=usage_types,
            facing=facing,
            furnishing_statuses=furnishing_statuses,
            infrastructure_terms=infrastructure_terms,
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
            locations=locations,
            statuses=statuses,
            usage_types=usage_types,
            facing=facing,
            furnishing_statuses=furnishing_statuses,
            infrastructure_terms=infrastructure_terms,
            keywords=tenant_keywords,
            price_per_sq_ft_lt=price_lt,
            price_per_sq_ft_gt=price_gt,
            sq_ft_gte=sq_ft_gte,
            sale_price_lt=sale_price_lt,
            sale_price_gt=sale_price_gt,
            cap_rate_gte=cap_rate_gte,
            cap_rate_lte=cap_rate_lte,
            sq_ft_lte=sq_ft_lte,
            availability_before=availability_before,
            clear_height_ft_gte=clear_height_ft_gte,
            dock_doors_gte=dock_doors_gte,
            trailer_parking_spaces_gte=trailer_parking_spaces_gte,
            parking_spaces_gte=parking_spaces_gte,
            require_immediate=require_immediate,
            sort="tenant_fit",
            requires_coordinates=requires_coordinates,
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
            locations=locations,
            statuses=statuses,
            usage_types=usage_types,
            facing=facing,
            furnishing_statuses=furnishing_statuses,
            infrastructure_terms=infrastructure_terms,
            keywords=keywords,
            price_per_sq_ft_lt=price_lt,
            price_per_sq_ft_gt=price_gt,
            sale_price_lt=sale_price_lt,
            sale_price_gt=sale_price_gt,
            cap_rate_gte=cap_rate_gte,
            cap_rate_lte=cap_rate_lte,
            sq_ft_gte=sq_ft_gte,
            sq_ft_lte=sq_ft_lte,
            clear_height_ft_gte=clear_height_ft_gte,
            dock_doors_gte=dock_doors_gte,
            trailer_parking_spaces_gte=trailer_parking_spaces_gte,
            parking_spaces_gte=parking_spaces_gte,
            availability_before=availability_before,
            require_immediate=require_immediate,
            requires_coordinates=requires_coordinates,
            aggregate=aggregate,
            aggregate_field=aggregate_field,
            limit=limit,
        )

    sort: str | None = None
    if any(term in normalized for term in ("lowest sale price", "cheapest to buy", "least expensive to buy")):
        sort = "sale_price_asc"
        reason_codes.append("sort_sale_price")
    elif any(term in normalized for term in ("cheapest", "lowest rent", "lowest price")):
        sort = "price_asc"
        reason_codes.append("sort_price")
    elif any(term in normalized for term in ("highest cap rate", "best cap rate")):
        sort = "cap_rate_desc"
        reason_codes.append("sort_cap_rate")
    elif any(term in normalized for term in ("largest", "biggest", "most square")):
        sort = "size_desc"
        reason_codes.append("sort_size")
    elif any(term in normalized for term in ("soonest", "earliest", "available first")):
        sort = "availability_asc"
        reason_codes.append("sort_availability")

    asks_for_inventory = _asks_for_inventory(normalized)
    has_structured_signal = bool(
        property_types
        or address_terms
        or uploader_names
        or markets
        or locations
        or statuses
        or usage_types
        or facing
        or furnishing_statuses
        or infrastructure_terms
        or keywords
        or price_lt is not None
        or price_gt is not None
        or sale_price_lt is not None
        or sale_price_gt is not None
        or cap_rate_gte is not None
        or cap_rate_lte is not None
        or sq_ft_gte is not None
        or sq_ft_lte is not None
        or clear_height_ft_gte is not None
        or dock_doors_gte is not None
        or trailer_parking_spaces_gte is not None
        or parking_spaces_gte is not None
        or availability_before is not None
        or requires_coordinates
        or sort is not None
    )
    asks_for_listing = _asks_for_listing(normalized)

    if address_terms and any(term in normalized for term in ("know about", "details", "detail", "tell me about")):
        intent = "exact_lookup"
        confidence = Decimal("0.9400")
        reason_codes.append("exact_lookup")
        property_types = []
        statuses = []
        usage_types = []
        facing = []
        furnishing_statuses = []
        infrastructure_terms = []
        keywords = []
    elif asks_for_inventory and not has_structured_signal:
        intent = "inventory_overview"
        confidence = Decimal("0.8600")
        limit = _inventory_limit(normalized, limit)
        reason_codes.extend(["broad_inventory", "structured_property_search", "toolhouse_escalation_available"])
    elif has_structured_signal and (
        asks_for_listing
        or property_types
        or price_lt is not None
        or price_gt is not None
        or sale_price_lt is not None
        or sale_price_gt is not None
        or cap_rate_gte is not None
        or cap_rate_lte is not None
        or sq_ft_gte is not None
        or sq_ft_lte is not None
        or clear_height_ft_gte is not None
        or dock_doors_gte is not None
        or trailer_parking_spaces_gte is not None
        or parking_spaces_gte is not None
    ):
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
        locations=locations,
        statuses=statuses,
        usage_types=usage_types,
        facing=facing,
        furnishing_statuses=furnishing_statuses,
        infrastructure_terms=infrastructure_terms,
        keywords=keywords,
        price_per_sq_ft_lt=price_lt,
        price_per_sq_ft_gt=price_gt,
        sale_price_lt=sale_price_lt,
        sale_price_gt=sale_price_gt,
        cap_rate_gte=cap_rate_gte,
        cap_rate_lte=cap_rate_lte,
        sq_ft_gte=sq_ft_gte,
        sq_ft_lte=sq_ft_lte,
        clear_height_ft_gte=clear_height_ft_gte,
        dock_doors_gte=dock_doors_gte,
        trailer_parking_spaces_gte=trailer_parking_spaces_gte,
        parking_spaces_gte=parking_spaces_gte,
        availability_before=availability_before,
        require_immediate=require_immediate,
        requires_coordinates=requires_coordinates,
        sort=sort,
        limit=limit,
    )


__all__ = ["DEMO_REFERENCE_DATE", "StructuredQuerySpec", "build_structured_query_spec"]
