from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class RetrievalDocument:
    """A source chunk prepared for local retrieval."""

    id: str
    text: str
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalHit:
    """A single retriever's ranked view of one document."""

    document_id: str
    retriever: str
    rank: int
    score: float
    matched_terms: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievalContribution:
    """Debug metadata retained after fusion."""

    retriever: str
    rank: int
    score: float
    matched_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class FusedCandidate:
    """A document selected after fusing one or more retrieval layers."""

    document: RetrievalDocument
    score: float
    contributions: tuple[RetrievalContribution, ...]
    matched_terms: tuple[str, ...] = ()
    metadata: Mapping[str, object] = field(default_factory=dict)
