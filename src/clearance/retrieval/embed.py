"""Embedding backends (plan T2.1).

The retriever depends only on the :class:`Embedder` protocol. Two backends:

- :class:`HashingEmbedder` — dependency-free, deterministic character-n-gram
  hashing into a sparse vector. Captures lexical/semantic overlap well enough
  for the tiny policy/chart corpora and runs under OFFLINE=1 with no downloads.
- :class:`LocalEmbedder` — real dense embeddings via ``sentence-transformers``
  (bge-small), lazily imported so it is only required when actually used.

Vectors are sparse ``dict[int, float]`` so cosine similarity is pure-Python.
"""

from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol, runtime_checkable

_TOKEN = re.compile(r"[a-z0-9]+")
Vector = dict[int, float]


@runtime_checkable
class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> Vector: ...


def _ngrams(tokens: list[str], n: int = 2) -> list[str]:
    grams = list(tokens)
    for i in range(len(tokens) - n + 1):
        grams.append(" ".join(tokens[i : i + n]))
    return grams


class HashingEmbedder:
    """Deterministic offline embedder: hashed bag of token (1,2)-grams."""

    def __init__(self, dim: int = 1024) -> None:
        self.dim = dim

    def _bucket(self, feature: str) -> int:
        h = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        return int.from_bytes(h, "big") % self.dim

    def embed(self, text: str) -> Vector:
        tokens = _TOKEN.findall(text.lower())
        vec: Vector = {}
        for feat in _ngrams(tokens):
            vec[self._bucket(feat)] = vec.get(self._bucket(feat), 0.0) + 1.0
        return _l2_normalize(vec)


class LocalEmbedder:  # pragma: no cover - requires an optional model download
    """Dense bge-small embeddings via sentence-transformers (production)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from sentence_transformers import SentenceTransformer  # type: ignore[import-not-found]

        self._model = SentenceTransformer(model_name)
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, text: str) -> Vector:
        dense = self._model.encode(text, normalize_embeddings=True)
        return {i: float(v) for i, v in enumerate(dense)}


def _l2_normalize(vec: Vector) -> Vector:
    norm = math.sqrt(sum(v * v for v in vec.values()))
    if norm == 0:
        return vec
    return {k: v / norm for k, v in vec.items()}


def cosine(a: Vector, b: Vector) -> float:
    if not a or not b:
        return 0.0
    # Iterate the smaller vector for speed.
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(k, 0.0) for k, v in a.items())
