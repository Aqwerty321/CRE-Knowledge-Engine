from __future__ import annotations

from app.retrieval.retrieval_types import RetrievalDocument, RetrievalHit
from app.retrieval.text_utils import matched_terms_in_text, normalize_text

try:
    from rapidfuzz import fuzz
except ImportError:  # pragma: no cover - fallback behavior is covered through disabled status
    fuzz = None

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except ImportError:  # pragma: no cover - fallback behavior is covered through disabled status
    TfidfVectorizer = None


class RapidFuzzRetriever:
    """Typo-tolerant matching for shorthand, partial names, and noisy phrasing."""

    name = "rapidfuzz"

    def __init__(self, *, enabled: bool = True, min_score: float = 0.55) -> None:
        self.enabled = enabled
        self.min_score = min_score

    @property
    def available(self) -> bool:
        return self.enabled and fuzz is not None

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

        normalized_query = normalize_text(query_text)
        probes = [normalized_query, *expanded_terms]
        scored: list[RetrievalHit] = []
        for document in documents:
            normalized_text = normalize_text(document.text)
            score = max(
                float(fuzz.partial_ratio(probe, normalized_text)) / 100.0
                for probe in probes
                if probe
            )
            if score < self.min_score:
                continue
            scored.append(
                RetrievalHit(
                    document_id=document.id,
                    retriever=self.name,
                    rank=0,
                    score=score,
                    matched_terms=matched_terms_in_text(document.text, expanded_terms),
                )
            )

        scored.sort(key=lambda item: item.score, reverse=True)
        return [
            RetrievalHit(
                document_id=hit.document_id,
                retriever=hit.retriever,
                rank=rank,
                score=hit.score,
                matched_terms=hit.matched_terms,
                metadata=hit.metadata,
            )
            for rank, hit in enumerate(scored[:limit], start=1)
        ]


class TfidfNgramRetriever:
    """Character n-gram retrieval for misspellings and light paraphrase overlap."""

    name = "tfidf_char"

    def __init__(self, *, enabled: bool = True, min_score: float = 0.04) -> None:
        self.enabled = enabled
        self.min_score = min_score

    @property
    def available(self) -> bool:
        return self.enabled and TfidfVectorizer is not None

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

        query = " ".join([normalize_text(query_text), *expanded_terms])
        try:
            vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), lowercase=True)
            document_matrix = vectorizer.fit_transform([document.text for document in documents])
            query_vector = vectorizer.transform([query])
            scores = (document_matrix @ query_vector.T).toarray().ravel()
        except Exception:  # noqa: BLE001 - local retrieval should degrade to other layers
            return []

        hits: list[RetrievalHit] = []
        for index, score in enumerate(scores):
            normalized_score = float(score)
            if normalized_score < self.min_score:
                continue
            document = documents[index]
            hits.append(
                RetrievalHit(
                    document_id=document.id,
                    retriever=self.name,
                    rank=0,
                    score=normalized_score,
                    matched_terms=matched_terms_in_text(document.text, expanded_terms),
                )
            )

        hits.sort(key=lambda item: item.score, reverse=True)
        return [
            RetrievalHit(
                document_id=hit.document_id,
                retriever=hit.retriever,
                rank=rank,
                score=hit.score,
                matched_terms=hit.matched_terms,
                metadata=hit.metadata,
            )
            for rank, hit in enumerate(hits[:limit], start=1)
        ]


__all__ = ["RapidFuzzRetriever", "TfidfNgramRetriever"]
