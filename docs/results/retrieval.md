# Clearance — Retrieval Evaluation

_10 policy queries · 74 evidence pairs · OFFLINE_

| Metric | Value |
| --- | --- |
| Policy RAG recall@3 (in-force criterion retrieved) | 100.0% |
| Evidence precision (structured refs vs engine ground truth) | 100.0% |
| Evidence recall | 100.0% |

Policy chunks are retrieved hybrid (BM25 ∪ embedding, RRF-fused) with the payer / procedure / effective-date filter applied inside the query. Evidence cards' structured references are scored against the resource ids the deterministic rules engine relied on, so recall/precision reflect true retrieval quality, not label noise.

> Offline runs use the dependency-free hashing embedder; production swaps in > bge-small dense embeddings and pgvector behind the same interface, which > raises semantic recall on free-text notes.

