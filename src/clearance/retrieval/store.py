"""Vector stores (plan T2.1).

The retriever depends on the :class:`VectorStore` protocol. Offline/tests use
:class:`InMemoryVectorStore` (pure-Python cosine). Production uses pgvector via
:class:`PgVectorStore`, which runs the same cosine search as a SQL query with
the payer/procedure/effective-date filter pushed *into* the query.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from clearance.retrieval.embed import Embedder, Vector, cosine


@dataclass
class StoredDoc:
    doc_id: str
    text: str
    vector: Vector
    metadata: dict[str, Any] = field(default_factory=dict)


class VectorStore(Protocol):
    def add(self, docs: list[StoredDoc]) -> None: ...
    def search(
        self, query_vec: Vector, top_k: int, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float]]: ...


def _matches(meta: dict[str, Any], where: dict[str, Any] | None) -> bool:
    """Apply equality + effective-date filters (pushed into the query)."""
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


class InMemoryVectorStore:
    def __init__(self) -> None:
        self._docs: list[StoredDoc] = []

    def add(self, docs: list[StoredDoc]) -> None:
        self._docs.extend(docs)

    def search(
        self, query_vec: Vector, top_k: int, where: dict[str, Any] | None = None
    ) -> list[tuple[str, float]]:
        scored = [
            (d.doc_id, cosine(query_vec, d.vector))
            for d in self._docs
            if _matches(d.metadata, where)
        ]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


def embed_docs(
    embedder: Embedder, items: list[tuple[str, str, dict[str, Any]]]
) -> list[StoredDoc]:
    """Build StoredDocs from (doc_id, text, metadata) triples."""
    return [StoredDoc(doc_id, text, embedder.embed(text), meta) for doc_id, text, meta in items]
