"""Retrieval eval thresholds (plan T2.3)."""

from __future__ import annotations

from evals.retrieval_eval import run


def test_retrieval_quality_thresholds() -> None:
    m = run(k=3)
    assert m.policy_queries >= 6
    assert m.evidence_pairs >= 20
    assert m.policy_recall_at_k >= 0.95
    assert m.evidence_precision >= 0.95
    assert m.evidence_recall >= 0.95
