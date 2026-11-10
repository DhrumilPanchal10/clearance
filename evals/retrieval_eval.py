"""Retrieval evaluation (plan T2.3).

Two measurements over labelled pairs, written to ``docs/results/retrieval.md``:

- **Policy RAG recall@k** — querying the criterion-chunk index with a criterion's
  own text (filtered to the in-force payer/procedure/date) should return that
  criterion in the top-k.
- **Evidence recall/precision** — the retrieval-backed evidence card's structured
  ``fhir_refs`` are scored against ground truth: the resource ids the
  deterministic rules engine relied on for the same facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from clearance.fhir.evidence_cards import ChartSlice, EvidenceCardBuilder
from clearance.policies.checklist import load_checklist
from clearance.policies.rules import build_facts, evaluate, parse_rule_spec
from clearance.retrieval.policy_rag import PolicyIndex
from evals.generate import PARSED, PROCEDURES
from evals.schema import load_cases

RESULTS_DIR = Path("docs/results")
_SPECS = {
    "lumbar_spine_mri": {"payer": "medicare", "procedure": "lumbar_spine_mri", "version": "L34220", "effective_from": "2015-10-01", "effective_to": None},
    "knee_mri": {"payer": "medicare", "procedure": "knee_mri", "version": "NCD-220.2", "effective_from": "2003-01-01", "effective_to": None},
    "ct_abdomen": {"payer": "medicare", "procedure": "ct_abdomen", "version": "L34415", "effective_from": "2015-10-01", "effective_to": None},
}


@dataclass
class RetrievalMetrics:
    policy_queries: int = 0
    policy_hits_at_k: int = 0
    evidence_pairs: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def policy_recall_at_k(self) -> float:
        return self.policy_hits_at_k / self.policy_queries if self.policy_queries else 1.0

    @property
    def evidence_precision(self) -> float:
        d = self.tp + self.fp
        return self.tp / d if d else 1.0

    @property
    def evidence_recall(self) -> float:
        d = self.tp + self.fn
        return self.tp / d if d else 1.0


def _expected_refs(criterion: dict, chart: ChartSlice) -> list[str]:
    facts = build_facts(_as_resources(chart), date.fromisoformat(chart.as_of))
    res = evaluate(parse_rule_spec(criterion["rule_spec"]), facts)
    return res.evidence_refs


def _as_resources(chart: ChartSlice) -> list[dict]:
    out: list[dict] = []
    for c in chart.conditions:
        out.append({"resourceType": "Condition", "id": c["id"], "code": {"coding": [{"code": x} for x in c["codes"]]}, "onsetDateTime": c.get("date")})
    for p in chart.procedures:
        out.append({"resourceType": "Procedure", "id": p["id"], "code": {"coding": [{"code": x} for x in p["codes"]]}, "performedDateTime": p.get("date")})
    for m in chart.medications:
        out.append({"resourceType": "MedicationRequest", "id": m["id"], "medicationCodeableConcept": {"coding": [{"code": x} for x in m["codes"]]}, "authoredOn": m.get("date")})
    return out


def run(k: int = 3) -> RetrievalMetrics:
    m = RetrievalMetrics()

    # Policy RAG recall@k.
    index = PolicyIndex()
    checklists = {}
    for proc in PROCEDURES:
        cl = load_checklist(PARSED[proc])
        checklists[proc] = cl
        index.add_checklist(cl, **_SPECS[proc])
    for proc in PROCEDURES:
        for crit in checklists[proc].criteria:
            hits = index.search(crit.text, payer="medicare", procedure=proc, as_of="2020-06-01", top_k=k)
            m.policy_queries += 1
            if crit.id in {h["criterion_id"] for h in hits}:
                m.policy_hits_at_k += 1

    # Evidence recall/precision over rule criteria in the generated cases.
    builder = EvidenceCardBuilder()
    for case in load_cases():
        chart = ChartSlice(
            as_of=case.as_of,
            conditions=[{"id": r.id, "codes": r.codes, "date": r.date} for r in case.conditions],
            procedures=[{"id": r.id, "codes": r.codes, "date": r.date} for r in case.procedures],
            medications=[{"id": r.id, "codes": r.codes, "date": r.date} for r in case.medications],
        )
        cl = checklists[case.procedure]
        for crit in cl.criteria:
            if crit.kind != "rule":
                continue
            cd = crit.model_dump()
            expected = set(_expected_refs(cd, chart))
            got = set(builder.build(f"{case.case_id}", cd, chart).fhir_refs)
            m.evidence_pairs += 1
            m.tp += len(expected & got)
            m.fp += len(got - expected)
            m.fn += len(expected - got)
    return m


def write_report(k: int = 3, out_dir: Path = RESULTS_DIR) -> Path:
    m = run(k)
    out_dir.mkdir(parents=True, exist_ok=True)
    body = [
        "# Clearance — Retrieval Evaluation",
        "",
        f"_{m.policy_queries} policy queries · {m.evidence_pairs} evidence pairs · OFFLINE_",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Policy RAG recall@{k} (in-force criterion retrieved) | {m.policy_recall_at_k:.1%} |",
        f"| Evidence precision (structured refs vs engine ground truth) | {m.evidence_precision:.1%} |",
        f"| Evidence recall | {m.evidence_recall:.1%} |",
        "",
        "Policy chunks are retrieved hybrid (BM25 ∪ embedding, RRF-fused) with the "
        "payer / procedure / effective-date filter applied inside the query. Evidence "
        "cards' structured references are scored against the resource ids the "
        "deterministic rules engine relied on, so recall/precision reflect true "
        "retrieval quality, not label noise.",
        "",
        "> Offline runs use the dependency-free hashing embedder; production swaps in "
        "> bge-small dense embeddings and pgvector behind the same interface, which "
        "> raises semantic recall on free-text notes.",
        "",
    ]
    path = out_dir / "retrieval.md"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    metrics = run()
    print(f"policy recall@3={metrics.policy_recall_at_k:.1%}  "
          f"evidence P={metrics.evidence_precision:.1%} R={metrics.evidence_recall:.1%}")
    print(f"Wrote {write_report()}")
