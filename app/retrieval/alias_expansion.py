from __future__ import annotations

from dataclasses import dataclass, field

from app.retrieval.retrieval_config import HybridRetrievalConfig
from app.retrieval.text_utils import contains_phrase, dedupe_strings, normalize_text

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - dependency fallback is exercised through availability status
    fuzz = None


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
        if fuzz is None or len(normalized_phrase) < 5:
            return False
        return float(fuzz.partial_ratio(normalized_phrase, normalized_query)) >= self.fuzzy_threshold


__all__ = ["AliasExpander", "QueryExpansion"]
