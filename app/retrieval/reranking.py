from __future__ import annotations

from collections.abc import Awaitable, Callable

from app.retrieval.retrieval_types import FusedCandidate, RetrievalContribution

RerankHook = Callable[[str, list[str]], Awaitable[dict[int, float]]]


class HybridReranker:
    """Optional final reranking hook for fused candidates."""

    def __init__(self, *, enabled: bool = True, blend_weight: float = 0.25) -> None:
        self.enabled = enabled
        self.blend_weight = max(0.0, min(1.0, blend_weight))

    async def rerank(
        self,
        query: str,
        candidates: list[FusedCandidate],
        *,
        hook: RerankHook | None = None,
    ) -> tuple[list[FusedCandidate], str]:
        if not self.enabled:
            return candidates, "disabled"
        if hook is None or not candidates:
            return candidates, "unavailable"

        try:
            scores = await hook(query, [candidate.document.text[:3000] for candidate in candidates])
        except Exception:  # noqa: BLE001 - retrieval should not fail if reranking is unavailable
            return candidates, "unavailable"
        if not scores:
            return candidates, "unavailable"

        reranked: list[FusedCandidate] = []
        for index, candidate in enumerate(candidates):
            rerank_score = max(0.0, min(1.0, float(scores.get(index, 0.0))))
            blended_score = ((1.0 - self.blend_weight) * candidate.score) + (self.blend_weight * rerank_score)
            reranked.append(
                FusedCandidate(
                    document=candidate.document,
                    score=blended_score,
                    contributions=(
                        *candidate.contributions,
                        RetrievalContribution(
                            retriever="rerank",
                            rank=index + 1,
                            score=rerank_score,
                            matched_terms=(),
                        ),
                    ),
                    matched_terms=candidate.matched_terms,
                    metadata=candidate.metadata,
                )
            )

        reranked.sort(key=lambda item: item.score, reverse=True)
        return reranked, "ok"


__all__ = ["HybridReranker", "RerankHook"]
