from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.retrieval.text_utils import dedupe_strings, normalize_text


DEFAULT_WEIGHTS = {
    "bm25": 1.00,
    "substring": 0.55,
    "rapidfuzz": 0.85,
    "tfidf_char": 0.75,
    "qdrant_vector": 1.10,
    "rerank": 1.20,
}

DEFAULT_ENABLED_RETRIEVERS = {
    "bm25": True,
    "substring": True,
    "rapidfuzz": True,
    "tfidf_char": True,
    "qdrant_vector": True,
    "rerank": True,
}


@dataclass(frozen=True)
class HybridRetrievalConfig:
    """Configuration for local hybrid retrieval.

    Domain-specific terms live in JSON config. Core retrievers only receive the
    normalized concepts, aliases, and weights from this object.
    """

    concepts: dict[str, tuple[str, ...]] = field(default_factory=dict)
    aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    enabled_retrievers: dict[str, bool] = field(default_factory=lambda: dict(DEFAULT_ENABLED_RETRIEVERS))
    rrf_k: int = 60
    limit: int = 10
    candidate_limit: int = 30
    fuzzy_min_score: float = 0.55
    tfidf_min_score: float = 0.04
    rerank_blend_weight: float = 0.25

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> HybridRetrievalConfig:
        concepts = {
            normalize_text(key): dedupe_strings(values)
            for key, values in dict(payload.get("concepts") or {}).items()
            if isinstance(values, list)
        }
        aliases = {
            normalize_text(key): dedupe_strings(values)
            for key, values in dict(payload.get("aliases") or {}).items()
            if isinstance(values, list)
        }
        weights = {**DEFAULT_WEIGHTS, **{str(key): float(value) for key, value in dict(payload.get("weights") or {}).items()}}
        enabled = {
            **DEFAULT_ENABLED_RETRIEVERS,
            **{str(key): bool(value) for key, value in dict(payload.get("enabled_retrievers") or {}).items()},
        }
        return cls(
            concepts=concepts,
            aliases=aliases,
            weights=weights,
            enabled_retrievers=enabled,
            rrf_k=int(payload.get("rrf_k") or 60),
            limit=int(payload.get("limit") or 10),
            candidate_limit=int(payload.get("candidate_limit") or 30),
            fuzzy_min_score=float(payload.get("fuzzy_min_score") or 0.55),
            tfidf_min_score=float(payload.get("tfidf_min_score") or 0.04),
            rerank_blend_weight=float(payload.get("rerank_blend_weight") or 0.25),
        )

    def concept_terms(self, concept: str | None) -> tuple[str, ...]:
        if concept is None:
            return ()
        return self.concepts.get(normalize_text(concept), ())

    def weight_for(self, retriever: str) -> float:
        return float(self.weights.get(retriever, 1.0))

    def retriever_enabled(self, retriever: str) -> bool:
        return bool(self.enabled_retrievers.get(retriever, True))


def _default_config_path() -> Path:
    return Path(__file__).with_name("retrieval_config.json")


def _read_config_payload(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


@lru_cache(maxsize=8)
def _load_hybrid_retrieval_config_for_path(path: str) -> HybridRetrievalConfig:
    configured_path = Path(path)
    payload = _read_config_payload(configured_path)
    if not payload and configured_path != _default_config_path():
        payload = _read_config_payload(_default_config_path())
    return HybridRetrievalConfig.from_mapping(payload)


def load_hybrid_retrieval_config(path: str | None = None) -> HybridRetrievalConfig:
    configured_path = Path(path) if path else get_settings().retrieval_config_path
    return _load_hybrid_retrieval_config_for_path(str(configured_path))


__all__ = ["HybridRetrievalConfig", "load_hybrid_retrieval_config"]
