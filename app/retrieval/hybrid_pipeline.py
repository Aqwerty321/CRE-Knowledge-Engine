from __future__ import annotations

from dataclasses import dataclass

from app.retrieval.alias_expansion import AliasExpander, QueryExpansion
from app.retrieval.fusion import ReciprocalRankFusion
from app.retrieval.fuzzy_retriever import RapidFuzzRetriever, TfidfNgramRetriever
from app.retrieval.lexical_retriever import BM25LexicalRetriever, SubstringLexicalRetriever
from app.retrieval.reranking import HybridReranker, RerankHook
from app.retrieval.retrieval_config import HybridRetrievalConfig
from app.retrieval.retrieval_types import FusedCandidate, RetrievalDocument, RetrievalHit


@dataclass(frozen=True)
class HybridPipelineResult:
    candidates: list[FusedCandidate]
    expansion: QueryExpansion
    layer_status: dict[str, str]
    rerank_status: str


class LocalHybridRetrievalPipeline:
    """Local lexical, fuzzy, and optional semantic-fusion retrieval pipeline."""

    def __init__(self, config: HybridRetrievalConfig) -> None:
        self.config = config
        self.expander = AliasExpander(config)
        self.fusion = ReciprocalRankFusion(k=config.rrf_k, weights=config.weights)

    async def retrieve(
        self,
        query: str,
        documents: list[RetrievalDocument],
        *,
        concept: str | None = None,
        limit: int | None = None,
        external_results: list[RetrievalHit] | None = None,
        rerank_hook: RerankHook | None = None,
    ) -> HybridPipelineResult:
        limit = limit or self.config.limit
        expansion = self.expander.expand(query, concept=concept)
        expanded_query = expansion.expanded_query_text()

        retrievers = [
            BM25LexicalRetriever(enabled=self.config.retriever_enabled("bm25")),
            SubstringLexicalRetriever(enabled=self.config.retriever_enabled("substring")),
            RapidFuzzRetriever(
                enabled=self.config.retriever_enabled("rapidfuzz"),
                min_score=self.config.fuzzy_min_score,
            ),
            TfidfNgramRetriever(
                enabled=self.config.retriever_enabled("tfidf_char"),
                min_score=self.config.tfidf_min_score,
            ),
        ]

        layer_status: dict[str, str] = {}
        result_sets: list[list[RetrievalHit]] = []
        for retriever in retrievers:
            if not retriever.available:
                layer_status[retriever.name] = "disabled" if not retriever.enabled else "unavailable"
                continue
            hits = retriever.retrieve(
                expanded_query,
                documents,
                expanded_terms=expansion.expanded_terms,
                limit=self.config.candidate_limit,
            )
            layer_status[retriever.name] = "ok" if hits else "empty"
            if hits:
                result_sets.append(hits)

        if external_results:
            result_sets.append(external_results)
            layer_status[external_results[0].retriever] = "ok"

        fused = self.fusion.fuse(documents, result_sets, limit=limit)
        reranker = HybridReranker(
            enabled=self.config.retriever_enabled("rerank"),
            blend_weight=self.config.rerank_blend_weight,
        )
        reranked, rerank_status = await reranker.rerank(expanded_query, fused, hook=rerank_hook)
        layer_status["rerank"] = rerank_status
        return HybridPipelineResult(
            candidates=reranked[:limit],
            expansion=expansion,
            layer_status=layer_status,
            rerank_status=rerank_status,
        )


__all__ = ["HybridPipelineResult", "LocalHybridRetrievalPipeline"]
