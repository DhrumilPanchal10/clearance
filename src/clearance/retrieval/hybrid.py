"""Hybrid retriever: BM25 ∪ vector via RRF, with optional rerank (plan T2.1).

Lexical (BM25) and semantic (vector cosine) candidate lists are fused with
Reciprocal Rank Fusion, then optionally reranked by a cross-encoder. Filters
(payer, procedure, effective date) are applied **inside** each candidate query,
not as a post-filter, so recall isn't lost to irrelevant tenants/policies.
Dependency-free offline; a real cross-encoder plugs into ``rerank``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from clearance.retrieval.bm25 import BM25
from clearance.retrieval.embed import Embedder, HashingEmbedder
from clearance.retrieval.store import InMemoryVectorStore, StoredDoc


@dataclass
class Document:
    doc_id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Hit:
    doc_id: str
    text: str
    score: float
    metadata: dict[str, Any]


Reranker = Callable[[str, list[Hit]], list[Hit]]


def reciprocal_rank_fusion(
    rankings: list[list[str]], k: int = 60
) -> list[tuple[str, float]]:
    """Fuse ranked id lists; score = Σ 1/(k + rank)."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank + 1)
    return sorted(scores.items(), key=lambda x: x[1], reverse=True)


class HybridRetriever:
    def __init__(self, embedder: Embedder | None = None, rerank: Reranker | None = None) -> None:
        self._embedder = embedder or HashingEmbedder()
        self._rerank = rerank
        self._bm25 = BM25()
        self._vectors = InMemoryVectorStore()
        self._docs: list[Document] = []

    def index(self, docs: list[Document]) -> None:
        self._docs = list(docs)
        self._bm25.index([d.text for d in docs])
        self._vectors.add(
            [StoredDoc(d.doc_id, d.text, self._embedder.embed(d.text), d.metadata) for d in docs]
        )

    def search(
        self, query: str, top_k: int = 5, where: dict[str, Any] | None = None
    ) -> list[Hit]:
        allowed = {d.doc_id for d in self._docs if _passes(d.metadata, where)}
        by_id = {d.doc_id: d for d in self._docs}
        idx_to_id = {i: d.doc_id for i, d in enumerate(self._docs)}

        lex = [
            idx_to_id[i]
            for i, _ in self._bm25.rank(query)
            if idx_to_id[i] in allowed
        ]
        sem = [
            doc_id
            for doc_id, _ in self._vectors.search(self._embedder.embed(query), top_k * 4, where)
            if doc_id in allowed
        ]
        fused = reciprocal_rank_fusion([lex, sem])
        hits = [
            Hit(doc_id, by_id[doc_id].text, score, by_id[doc_id].metadata)
            for doc_id, score in fused
            if doc_id in by_id
        ]
        if self._rerank:
            hits = self._rerank(query, hits)
        return hits[:top_k]


def _passes(meta: dict[str, Any], where: dict[str, Any] | None) -> bool:
    if not where:
        return True
    for key, cond in where.items():
        if key == "as_of":
            ef, et = meta.get("effective_from"), meta.get("effective_to")
            if ef and cond < ef:
                return False
            if et and cond >= et:
                return False
        elif meta.get(key) != cond:
            return False
    return True
