from __future__ import annotations

from collections import defaultdict

from app.retrieval.retrieval_types import FusedCandidate, RetrievalContribution, RetrievalDocument, RetrievalHit
from app.retrieval.text_utils import dedupe_strings


class ReciprocalRankFusion:
    """Rank-based fusion that does not require scores to share a scale."""

    def __init__(self, *, k: int = 60, weights: dict[str, float] | None = None) -> None:
        self.k = max(1, k)
        self.weights = weights or {}

    def fuse(
        self,
        documents: list[RetrievalDocument],
        result_sets: list[list[RetrievalHit]],
        *,
        limit: int = 10,
    ) -> list[FusedCandidate]:
        document_by_id = {document.id: document for document in documents}
        fused_scores: dict[str, float] = defaultdict(float)
        contributions: dict[str, list[RetrievalContribution]] = defaultdict(list)
        matched_terms: dict[str, list[str]] = defaultdict(list)

        for hits in result_sets:
            for hit in hits:
                if hit.document_id not in document_by_id:
                    continue
                weight = float(self.weights.get(hit.retriever, 1.0))
                rank = max(1, hit.rank)
                fused_scores[hit.document_id] += weight / (self.k + rank)
                contributions[hit.document_id].append(
                    RetrievalContribution(
                        retriever=hit.retriever,
                        rank=rank,
                        score=hit.score,
                        matched_terms=hit.matched_terms,
                    )
                )
                matched_terms[hit.document_id].extend(hit.matched_terms)

        max_score = max(fused_scores.values(), default=0.0)
        candidates: list[FusedCandidate] = []
        for document_id, score in fused_scores.items():
            document = document_by_id[document_id]
            normalized_score = score / max_score if max_score else 0.0
            candidates.append(
                FusedCandidate(
                    document=document,
                    score=normalized_score,
                    contributions=tuple(sorted(contributions[document_id], key=lambda item: (item.rank, item.retriever))),
                    matched_terms=dedupe_strings(matched_terms[document_id]),
                    metadata=document.metadata,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:limit]


__all__ = ["ReciprocalRankFusion"]
