from __future__ import annotations

from dataclasses import dataclass, field
from math import isnan
from typing import Any

from app.retrieval.retrieval_config import HybridRetrievalConfig
from app.retrieval.text_utils import contains_phrase, dedupe_strings, normalize_text

try:
    from polyfuzz import PolyFuzz
except ImportError:  # pragma: no cover - dependency fallback is exercised through availability status
    PolyFuzz = None


def _polyfuzz_similarity(model: Any, source: str, target: str) -> float:
    if not source or not target:
        return 0.0
    try:
        model.match([source], [target])
        matches = model.get_matches()
        if matches.empty:
            return 0.0
        raw_score: Any = matches.iloc[0].get("Similarity", 0.0)
        score = float(raw_score)
    except Exception:  # noqa: BLE001 - alias expansion can continue without fuzzy matching
        return 0.0
    return 0.0 if isnan(score) else max(0.0, min(1.0, score))


def _windows(value: str, *, token_count: int) -> tuple[str, ...]:
    tokens = value.split()
    if token_count <= 0 or len(tokens) < token_count:
        return ()
    return tuple(" ".join(tokens[index : index + token_count]) for index in range(0, len(tokens) - token_count + 1))


@dataclass(frozen=True)
class QueryExpansion:
    original_query: str
    normalized_query: str
    expanded_terms: tuple[str, ...]
    matched_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)

    def expanded_query_text(self) -> str:
        return " ".join(dedupe_strings([self.normalized_query, *self.expanded_terms]))


class AliasExpander:
    """Expands query terms from a configurable alias dictionary."""

    def __init__(self, config: HybridRetrievalConfig, *, fuzzy_threshold: float = 84.0) -> None:
        self.config = config
        self.fuzzy_threshold = fuzzy_threshold

    def expand(self, query: str, *, concept: str | None = None) -> QueryExpansion:
        normalized_query = normalize_text(query)
        concept_terms = set(self.config.concept_terms(concept))
        terms: list[str] = list(concept_terms)
        matched_aliases: dict[str, tuple[str, ...]] = {}

        for alias, expansions in self.config.aliases.items():
            if concept_terms and not (set(expansions) & concept_terms or alias in concept_terms):
                continue
            if self._query_matches_phrase(normalized_query, alias):
                matched_aliases[alias] = expansions
                terms.extend(expansions)

        return QueryExpansion(
            original_query=query,
            normalized_query=normalized_query,
            expanded_terms=dedupe_strings(terms),
            matched_aliases=matched_aliases,
        )

    def matches_concept(self, query: str, concept: str) -> bool:
        normalized_query = normalize_text(query)
        concept_terms = set(self.config.concept_terms(concept))
        if not concept_terms:
            return False

        concept_vocabulary: set[str] = set(concept_terms)
        for alias, expansions in self.config.aliases.items():
            expansion_set = set(expansions)
            if concept_terms & expansion_set:
                concept_vocabulary.add(alias)
                concept_vocabulary.update(expansion_set)

        return any(self._query_matches_phrase(normalized_query, phrase) for phrase in concept_vocabulary)

    def _query_matches_phrase(self, normalized_query: str, phrase: str) -> bool:
        normalized_phrase = normalize_text(phrase)
        if not normalized_phrase:
            return False
        if contains_phrase(normalized_query, normalized_phrase):
            return True
        if PolyFuzz is None or len(normalized_phrase) < 5:
            return False
        token_count = len(normalized_phrase.split())
        candidates = (normalized_query, *_windows(normalized_query, token_count=token_count), *_windows(normalized_query, token_count=token_count + 1))
        model = PolyFuzz("EditDistance")
        return max((_polyfuzz_similarity(model, normalized_phrase, candidate) for candidate in candidates), default=0.0) >= (
            self.fuzzy_threshold / 100.0
        )


__all__ = ["AliasExpander", "QueryExpansion"]
