from __future__ import annotations

from app.retrieval.retrieval_types import RetrievalDocument, RetrievalHit
from app.retrieval.text_utils import matched_terms_in_text

try:
    import bm25s
except ImportError:  # pragma: no cover - fallback behavior is covered through disabled status
    bm25s = None


class BM25LexicalRetriever:
    """BM25S-backed lexical retrieval over an in-memory chunk corpus."""

    name = "bm25"

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    @property
    def available(self) -> bool:
        return self.enabled and bm25s is not None

    def retrieve(
        self,
        query_text: str,
        documents: list[RetrievalDocument],
        *,
        expanded_terms: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[RetrievalHit]:
        if not self.available or not documents:
            return []

        try:
            corpus_tokens = bm25s.tokenize([document.text for document in documents])
            retriever = bm25s.BM25()
            retriever.index(corpus_tokens)
            query_tokens = bm25s.tokenize([query_text])
            results = retriever.retrieve(query_tokens, k=min(limit, len(documents)))
        except Exception:  # noqa: BLE001 - local retrieval should degrade to other layers
            return []

        doc_indexes = list(results.documents[0]) if len(results.documents) else []
        scores = [float(score) for score in list(results.scores[0])] if len(results.scores) else []
        max_score = max(scores, default=0.0)
        hits: list[RetrievalHit] = []
        for rank, (doc_index, raw_score) in enumerate(zip(doc_indexes, scores, strict=False), start=1):
            if raw_score <= 0:
                continue
            document = documents[int(doc_index)]
            normalized_score = raw_score / max_score if max_score else raw_score
            hits.append(
                RetrievalHit(
                    document_id=document.id,
                    retriever=self.name,
                    rank=rank,
                    score=normalized_score,
                    matched_terms=matched_terms_in_text(document.text, expanded_terms),
                )
            )
        return hits


class SubstringLexicalRetriever:
    """Standard-library lexical fallback for configured terms."""

    name = "substring"

    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    @property
    def available(self) -> bool:
        return self.enabled

    def retrieve(
        self,
        _query_text: str,
        documents: list[RetrievalDocument],
        *,
        expanded_terms: tuple[str, ...] = (),
        limit: int = 10,
    ) -> list[RetrievalHit]:
        if not self.available or not documents or not expanded_terms:
            return []

        scored: list[tuple[RetrievalDocument, tuple[str, ...]]] = []
        for document in documents:
            matches = matched_terms_in_text(document.text, expanded_terms)
            if matches:
                scored.append((document, matches))

        scored.sort(key=lambda item: (len(item[1]), item[0].metadata.get("address") or ""), reverse=True)
        return [
            RetrievalHit(
                document_id=document.id,
                retriever=self.name,
                rank=rank,
                score=min(1.0, len(matches) / max(1, len(expanded_terms))),
                matched_terms=matches,
            )
            for rank, (document, matches) in enumerate(scored[:limit], start=1)
        ]


__all__ = ["BM25LexicalRetriever", "SubstringLexicalRetriever"]
