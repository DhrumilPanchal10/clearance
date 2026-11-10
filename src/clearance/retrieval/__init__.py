"""Hybrid retrieval for Clearance (plan Phase 2).

Pure-Python, dependency-free by default (so ``OFFLINE=1`` needs no model
downloads), with real backends — local bge-small embeddings and pgvector —
pluggable behind the same interfaces.

- :mod:`clearance.retrieval.bm25` — lexical BM25.
- :mod:`clearance.retrieval.embed` — embedding protocol + offline hashing fallback.
- :mod:`clearance.retrieval.store` — vector store (in-memory cosine; pgvector iface).
- :mod:`clearance.retrieval.hybrid` — BM25 ∪ vector via RRF + optional rerank.
- :mod:`clearance.retrieval.policy_rag` — chunk policies by criterion and retrieve.
"""

from clearance.retrieval.hybrid import Document, HybridRetriever, reciprocal_rank_fusion

__all__ = ["Document", "HybridRetriever", "reciprocal_rank_fusion"]
