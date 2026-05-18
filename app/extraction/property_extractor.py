from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.extraction.parsers import ParsedChunk


ADDRESS_RE = re.compile(
    r"\b\d{2,6}\s+[A-Z][A-Za-z0-9.'-]*(?:\s+[A-Z][A-Za-z0-9.'-]*){0,5}\s+"
    r"(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Drive|Dr|Lane|Ln|Pkwy|Parkway|Way|Yard|Ct|Court|Loop)\b",
    re.IGNORECASE,
)
SQ_FT_RE = re.compile(
    r"(?P<value>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*(?P<suffix>k)?\s*(?:sf|sq\.?\s*ft|square\s+feet)\b",
    re.IGNORECASE,
)
PRICE_RE = re.compile(r"\$\s*(?P<value>\d+(?:\.\d+)?)\s*/\s*(?:sf|sq\.?\s*ft|sqft)", re.IGNORECASE)
MARKET_TERMS = [
    "midtown",
    "downtown",
    "harbor district",
    "airport submarket",
    "north loop",
    "riverfront",
    "central business district",
]
CRE_SIGNAL_TERMS = [
    "industrial",
    "office",
    "retail",
    "multifamily",
    "land",
    "warehouse",
    "logistics",
    "yard",
    "dock",
    "loading",
    "lease",
    "sublease",
    "listing",
    "availability",
    "inventory",
    "asking",
    "tenant",
]


@dataclass(frozen=True)
class ExtractedPropertyFact:
    address: str
    property_type: str
    chunk_index: int
    sq_ft: int | None
    price_per_sq_ft: Decimal | None
    availability: str | None
    availability_date: date | None
    market: str | None
    source_page: int | None
    source_row: int | None
    confidence: Decimal
    source_authority_score: Decimal
    freshness_score: Decimal


def _normalize_address(address: str) -> str:
    return " ".join(address.replace(",", " ").split())


def _extract_sq_ft(text: str) -> int | None:
    match = SQ_FT_RE.search(text)
    if not match:
        return None
    raw_value = match.group("value").replace(",", "")
    value = float(raw_value)
    if match.group("suffix"):
        value *= 1000
    return int(value)


def _extract_price(text: str) -> Decimal | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    return Decimal(match.group("value")).quantize(Decimal("0.01"))


def _extract_property_type(text: str) -> str:
    normalized = text.lower()
    for property_type in ("industrial", "office", "retail", "multifamily", "land"):
        if property_type in normalized:
            return property_type
    if "warehouse" in normalized or "logistics" in normalized:
        return "industrial"
    return "unknown"


def _extract_market(text: str) -> str | None:
    normalized = text.lower()
    for market in MARKET_TERMS:
        if market in normalized:
            return market.title()
    return None


def _extract_availability(text: str) -> tuple[str | None, date | None]:
    normalized = text.lower()
    if "immediate" in normalized or "available now" in normalized:
        return "Immediate", date(2026, 5, 17)

    month_match = re.search(
        r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(20\d{2})\b",
        normalized,
    )
    if month_match:
        month_map = {
            "jan": 1,
            "feb": 2,
            "mar": 3,
            "apr": 4,
            "may": 5,
            "jun": 6,
            "jul": 7,
            "aug": 8,
            "sep": 9,
            "sept": 9,
            "oct": 10,
            "nov": 11,
            "dec": 12,
        }
        month = month_map[month_match.group(1)]
        year = int(month_match.group(2))
        return f"{month_match.group(1).title()} {year}", date(year, month, 1)

    quarter_match = re.search(r"\bq([1-4])\s*(20\d{2})\b", normalized)
    if quarter_match:
        quarter = int(quarter_match.group(1))
        year = int(quarter_match.group(2))
        month = ((quarter - 1) * 3) + 1
        return f"Q{quarter} {year}", date(year, month, 1)

    return None, None


def _authority_for_source(source_type: str) -> Decimal:
    if source_type in {"pdf", "xlsx", "csv"}:
        return Decimal("0.7000")
    if source_type == "slack_message":
        return Decimal("0.5500")
    if source_type == "image":
        return Decimal("0.6000")
    return Decimal("0.5000")


def _confidence(property_type: str, sq_ft: int | None, price_per_sq_ft: Decimal | None) -> Decimal:
    score = Decimal("0.5500")
    if property_type != "unknown":
        score += Decimal("0.1000")
    if sq_ft is not None:
        score += Decimal("0.1000")
    if price_per_sq_ft is not None:
        score += Decimal("0.1000")
    return min(score, Decimal("0.8500"))


def _has_structured_cre_signal(
    *,
    property_type: str,
    sq_ft: int | None,
    price_per_sq_ft: Decimal | None,
    availability: str | None,
    market: str | None,
) -> bool:
    return any(
        (
            property_type != "unknown",
            sq_ft is not None,
            price_per_sq_ft is not None,
            availability is not None,
            market is not None,
        )
    )


def _cre_keyword_hit_count(text: str) -> int:
    normalized = text.lower()
    return sum(1 for term in CRE_SIGNAL_TERMS if term in normalized)


def has_cre_ingest_signal(text: str) -> bool:
    normalized_text = text.strip()
    if not normalized_text:
        return False

    addresses = ADDRESS_RE.findall(normalized_text)
    property_type = _extract_property_type(normalized_text)
    sq_ft = _extract_sq_ft(normalized_text)
    price_per_sq_ft = _extract_price(normalized_text)
    availability, _availability_date = _extract_availability(normalized_text)
    market = _extract_market(normalized_text)
    structured_signal_count = sum(
        1
        for signal in (
            property_type != "unknown",
            sq_ft is not None,
            price_per_sq_ft is not None,
            availability is not None,
            market is not None,
        )
        if signal
    )
    keyword_hits = _cre_keyword_hit_count(normalized_text)

    if addresses and (structured_signal_count >= 1 or keyword_hits >= 2):
        return True
    if structured_signal_count >= 2:
        return True
    if keyword_hits >= 3 and any((addresses, sq_ft is not None, price_per_sq_ft is not None)):
        return True
    return False


def has_structured_listing_signal(text: str) -> bool:
    normalized_text = text.strip()
    if not normalized_text:
        return False
    return bool(
        extract_property_facts(
            [ParsedChunk(chunk_index=0, text=normalized_text)],
            source_type="slack_message",
        )
    )


def extract_property_facts(chunks: list[ParsedChunk], *, source_type: str) -> list[ExtractedPropertyFact]:
    facts: list[ExtractedPropertyFact] = []
    seen: set[tuple[str, int]] = set()
    authority = _authority_for_source(source_type)

    for chunk in chunks:
        text = chunk.text.strip()
        if not text:
            continue
        addresses = ADDRESS_RE.findall(text)
        if not addresses:
            continue

        property_type = _extract_property_type(text)
        sq_ft = _extract_sq_ft(text)
        price_per_sq_ft = _extract_price(text)
        availability, availability_date = _extract_availability(text)
        market = _extract_market(text)
        if not _has_structured_cre_signal(
            property_type=property_type,
            sq_ft=sq_ft,
            price_per_sq_ft=price_per_sq_ft,
            availability=availability,
            market=market,
        ):
            continue

        for address in addresses[:3]:
            normalized_address = _normalize_address(address)
            key = (normalized_address.lower(), chunk.chunk_index)
            if key in seen:
                continue
            seen.add(key)
            facts.append(
                ExtractedPropertyFact(
                    address=normalized_address,
                    property_type=property_type,
                    chunk_index=chunk.chunk_index,
                    sq_ft=sq_ft,
                    price_per_sq_ft=price_per_sq_ft,
                    availability=availability,
                    availability_date=availability_date,
                    market=market,
                    source_page=chunk.page_number,
                    source_row=chunk.row_number,
                    confidence=_confidence(property_type, sq_ft, price_per_sq_ft),
                    source_authority_score=authority,
                    freshness_score=Decimal("0.6000"),
                )
            )

    return facts


__all__ = [
    "ExtractedPropertyFact",
    "extract_property_facts",
    "has_cre_ingest_signal",
    "has_structured_listing_signal",
]