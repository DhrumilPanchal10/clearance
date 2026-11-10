"""Pure-Python BM25 lexical retrieval (plan T2.1).

No external dependency (works under OFFLINE=1). Okapi BM25 over a small,
in-memory corpus — the policy criterion chunks and chart notes we index are
tiny, so a dependency-free implementation is both sufficient and reproducible.
A production swap to ``bm25s`` or a Postgres full-text index is behind the same
``rank`` interface.
"""

from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class BM25:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b
        self._docs: list[list[str]] = []
        self._freqs: list[Counter[str]] = []
        self._df: Counter[str] = Counter()
        self._avg_len = 0.0

    def index(self, docs: list[str]) -> None:
        self._docs = [tokenize(d) for d in docs]
        self._freqs = [Counter(toks) for toks in self._docs]
        self._df = Counter()
        for toks in self._freqs:
            self._df.update(set(toks))
        total = sum(len(d) for d in self._docs)
        self._avg_len = total / len(self._docs) if self._docs else 0.0

    def _idf(self, term: str) -> float:
        n = len(self._docs)
        df = self._df.get(term, 0)
        # BM25 idf with +1 smoothing (always positive).
        return math.log(1 + (n - df + 0.5) / (df + 0.5))

    def score(self, query: str, doc_index: int) -> float:
        toks = self._freqs[doc_index]
        dl = len(self._docs[doc_index])
        s = 0.0
        for term in set(tokenize(query)):
            if term not in toks:
                continue
            tf = toks[term]
            denom = tf + self.k1 * (1 - self.b + self.b * dl / (self._avg_len or 1))
            s += self._idf(term) * (tf * (self.k1 + 1)) / (denom or 1)
        return s

    def rank(self, query: str, top_k: int | None = None) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(len(self._docs))]
        scored = [(i, s) for i, s in scored if s > 0]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k] if top_k else scored
