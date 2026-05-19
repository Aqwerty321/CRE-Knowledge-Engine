from __future__ import annotations

import re
from collections.abc import Iterable


def normalize_text(value: str) -> str:
    """Normalize text for local lexical and fuzzy matching."""

    return " ".join(re.sub(r"[^a-z0-9$./]+", " ", value.lower()).split())


def contains_phrase(text: str, phrase: str) -> bool:
    normalized_text = normalize_text(text)
    normalized_phrase = normalize_text(phrase)
    if not normalized_phrase:
        return False
    if " " in normalized_phrase:
        return normalized_phrase in normalized_text
    return re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_text) is not None


def dedupe_strings(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    output: list[str] = []
    for value in values:
        normalized = normalize_text(value)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return tuple(output)


def matched_terms_in_text(text: str, terms: Iterable[str]) -> tuple[str, ...]:
    return dedupe_strings(term for term in terms if contains_phrase(text, term))
