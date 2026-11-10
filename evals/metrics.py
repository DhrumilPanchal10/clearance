"""Scoring: criteria accuracy, end-state, citations (plan T9.3).

The **citation judge** here is resolver-based and deterministic: a letter line
that makes a clinical claim is *supported* iff it carries at least one FHIR
reference and every referenced id resolves to a real resource in the patient's
chart. Citation precision = supported / claim-lines; unsupported-claim rate is
its complement. This needs no model and is fully reproducible; a model-based
judge (calibrated on hand-checked letters, see docs/results/judge_calibration.md)
would slot in behind the same interface.
"""

from __future__ import annotations

from dataclasses import dataclass

from evals.harness import CaseResult
from evals.schema import EvalCase


@dataclass
class Scored:
    case_id: str
    criteria_total: int
    criteria_correct: int
    end_state_correct: bool
    claim_lines: int
    supported_lines: int

    @property
    def criteria_accuracy(self) -> float:
        return self.criteria_correct / self.criteria_total if self.criteria_total else 1.0

    @property
    def all_criteria_correct(self) -> bool:
        return self.criteria_correct == self.criteria_total

    @property
    def citation_precision(self) -> float:
        return self.supported_lines / self.claim_lines if self.claim_lines else 1.0

    @property
    def unsupported_rate(self) -> float:
        return 1.0 - self.citation_precision


def score(case: EvalCase, result: CaseResult) -> Scored:
    correct = sum(
        1
        for cid, expected in case.expected_labels.items()
        if result.labels.get(cid) == expected
    )
    # Score citations only over lines that assert a positive chart finding.
    claim_lines = [ln for ln in result.letter_lines if ln.get("requires_citation")]
    supported = 0
    for ln in claim_lines:
        refs = ln.get("fhir_refs") or []
        if refs and all(r in result.known_refs for r in refs):
            supported += 1
    return Scored(
        case_id=case.case_id,
        criteria_total=len(case.expected_labels),
        criteria_correct=correct,
        end_state_correct=result.end_state == case.expected_end_state,
        claim_lines=len(claim_lines),
        supported_lines=supported,
    )


@dataclass
class Aggregate:
    n: int = 0
    criteria_total: int = 0
    criteria_correct: int = 0
    end_state_correct: int = 0
    pass_cases: int = 0  # all criteria + end state correct
    passk_cases: int = 0  # passed on every one of k repeats
    claim_lines: int = 0
    supported_lines: int = 0

    def add(self, s: Scored, passed_all_k: bool) -> None:
        self.n += 1
        self.criteria_total += s.criteria_total
        self.criteria_correct += s.criteria_correct
        self.end_state_correct += int(s.end_state_correct)
        self.pass_cases += int(s.all_criteria_correct and s.end_state_correct)
        self.passk_cases += int(passed_all_k)
        self.claim_lines += s.claim_lines
        self.supported_lines += s.supported_lines

    @property
    def criteria_accuracy(self) -> float:
        return self.criteria_correct / self.criteria_total if self.criteria_total else 1.0

    @property
    def end_state_accuracy(self) -> float:
        return self.end_state_correct / self.n if self.n else 1.0

    @property
    def pass_at_1(self) -> float:
        return self.pass_cases / self.n if self.n else 1.0

    @property
    def pass_at_k(self) -> float:
        return self.passk_cases / self.n if self.n else 1.0

    @property
    def citation_precision(self) -> float:
        return self.supported_lines / self.claim_lines if self.claim_lines else 1.0

    @property
    def unsupported_rate(self) -> float:
        return 1.0 - self.citation_precision
