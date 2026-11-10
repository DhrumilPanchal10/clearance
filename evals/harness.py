"""Run one eval case through the real agent graph + a naive baseline (T9.2/T9.3).

The **multi-agent system under test** is the production assess graph
(intake → policy ∥ evidence → criteria) with a fake FHIR tool serving the
case's facts: rule criteria are decided by the real deterministic engine, and
judgment criteria by an oracle stub (same label both systems see). It then
drafts the real cited letter.

The **baseline** is a single naive agent that decides *every* criterion the way
an LLM without a rules engine would — presence-of-code, ignoring thresholds,
date windows and negations — and writes an uncited letter. The comparison
isolates exactly what rules-in-code buys: correctness on quantitative/negation
criteria and verifiable citations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from agentcore.llm import _set_complete_fn
from clearance.agents.criteria import _JudgeResult, make_criteria_node
from clearance.agents.evidence import make_evidence_node
from clearance.agents.graphs import build_assess_graph
from clearance.agents.intake import make_intake_node
from clearance.agents.policy import make_policy_node
from clearance.agents.state import new_case_state
from clearance.agents.submission import make_submission_node
from clearance.policies.checklist import load_checklist as _load_file
from evals import clinician_sim
from evals.generate import PARSED
from evals.schema import EvalCase

_VERSIONS = {"lumbar_spine_mri": "L34220", "knee_mri": "NCD-220.2", "ct_abdomen": "L34415"}


@dataclass
class CaseResult:
    case_id: str
    procedure: str
    labels: dict[str, str]  # predicted criterion_id -> status
    end_state: str
    letter_lines: list[dict[str, Any]]  # {text, fhir_refs}
    known_refs: set[str] = field(default_factory=set)


def _fake_tools(case: EvalCase) -> SimpleNamespace:
    async def get_patient_facts(ctx: Any, *, patient_id: str) -> dict[str, Any]:
        return case.facts_payload()

    return SimpleNamespace(get_patient_facts=get_patient_facts)


async def _checklist_loader(payer: str, procedure: str, version: str) -> list[dict[str, Any]]:
    checklist = _load_file(PARSED[procedure])
    return [c.model_dump() for c in checklist.criteria]


async def _version_lookup(payer: str, procedure: str, as_of: str) -> str | None:
    return _VERSIONS.get(procedure)


def _oracle_judge(case: EvalCase, checklist: list[dict[str, Any]]):
    # A judgment criterion listed in hidden_facts is deliberately unresolved by
    # the chart: the judge returns 'unknown' to force the clinician gap-fill.
    by_text = {
        c["text"]: ("unknown" if c["id"] in case.hidden_facts else case.expected_labels.get(c["id"], "met"))
        for c in checklist
    }

    async def complete(messages: Any, *, schema: Any, **kwargs: Any) -> Any:
        user = next((m["content"] for m in messages if m["role"] == "user"), "")
        label = "met"
        for text, lab in by_text.items():
            if text and text in user:
                label = lab
                break
        return _JudgeResult(status=label, confidence=0.9, rationale="oracle")  # type: ignore[arg-type]

    return complete


def _apply_clinician(case: EvalCase, decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Gap-fill: a clinician answer resolves an unknown to met (T9.2 loop)."""
    out = []
    for d in decisions:
        if d["status"] == "unknown" and clinician_sim.answer(case, d["criterion_id"]):
            d = {**d, "status": "met", "method": "agent", "rationale": "clinician-provided"}
        out.append(d)
    return out


def _end_state(labels: dict[str, str]) -> str:
    vals = set(labels.values())
    if "unknown" in vals:
        return "needs_clinician"
    if "not_met" in vals:
        return "not_met"
    return "approved"


def _known_refs(case: EvalCase) -> set[str]:
    refs = {r.id for r in case.conditions + case.procedures + case.medications}
    return refs


def _requires_citation(criterion: dict[str, Any]) -> bool:
    """A line asserts a positive chart finding (so it must cite a resource).

    Age is demographic, judgment is narrative, and 'must_be_absent' rules assert
    an *absence* — none of these reference a chart resource, so they are not
    scored for citation.
    """
    if criterion.get("kind") != "rule":
        return False
    spec = criterion.get("rule_spec") or {}
    if spec.get("kind") == "age":
        return False
    if spec.get("must_be_absent"):
        return False
    return spec.get("kind") in {"diagnosis", "prior_procedure", "conservative_therapy"}


async def run_system(case: EvalCase) -> CaseResult:
    """Run the production multi-agent assess + draft on a case."""
    checklist = await _checklist_loader(case.payer, case.procedure, "")
    _set_complete_fn(_oracle_judge(case, checklist))
    try:
        tools = _fake_tools(case)
        graph = build_assess_graph(
            make_intake_node(_version_lookup),
            make_policy_node(_checklist_loader),
            make_evidence_node(tools, _checklist_loader),
            make_criteria_node(tools),
        )
        state = new_case_state(
            case_id=case.case_id,
            tenant_id="clinic-a",
            patient_id="pat",
            payer=case.payer,
            procedure=case.procedure,
            as_of=case.as_of,
        )
        assessed = await graph.ainvoke(dict(state))
        decisions = [d.model_dump() for d in assessed.get("decisions", [])]
        # Clinician gap-fill if the chart left anything unknown.
        if any(d["status"] == "unknown" for d in decisions):
            decisions = _apply_clinician(case, decisions)
        labels = {d["criterion_id"]: d["status"] for d in decisions}

        # Draft the cited letter (only when everything is met, like production).
        letter_lines: list[dict[str, Any]] = []
        if all(v == "met" for v in labels.values()):
            draft_state = {**assessed, "decisions": assessed.get("decisions", [])}
            drafted = await make_submission_node()(draft_state)
            letter = drafted.get("letter") or {}
            requires = {c["id"]: _requires_citation(c) for c in checklist}
            # Map each line back to its criterion via text to tag citation need.
            text_to_id = {c["text"]: c["id"] for c in checklist}
            for sec in letter.get("sections", []):
                for ln in sec.get("lines", []):
                    cid = text_to_id.get(ln.get("text", ""))
                    letter_lines.append({**ln, "requires_citation": requires.get(cid, False)})
        return CaseResult(
            case_id=case.case_id,
            procedure=case.procedure,
            labels=labels,
            end_state=_end_state(labels),
            letter_lines=letter_lines,
            known_refs=_known_refs(case),
        )
    finally:
        _set_complete_fn(None)


# --------------------------------------------------------------------------- #
# Baseline: a single naive agent, no rules engine, no citation discipline.
# --------------------------------------------------------------------------- #


def _naive_decide(spec: dict[str, Any], case: EvalCase) -> str:
    """How an LLM without a rules engine tends to decide: presence-of-code only.

    It ignores age ranges, date windows, duration thresholds, and negation
    (must_be_absent) — the exact places quantitative rules bite.
    """
    kind = spec.get("kind")
    if kind == "age":
        return "met" if case.birth_date else "unknown"
    codes = set(spec.get("any_of") or spec.get("codes") or [])
    present_buckets = {
        "diagnosis": [r.codes for r in case.conditions],
        "prior_procedure": [r.codes for r in case.procedures],
        "conservative_therapy": [r.codes for r in case.procedures + case.medications],
    }.get(kind, [])
    present = any(codes & set(cs) for cs in present_buckets)
    return "met" if present else "not_met"


async def run_baseline(case: EvalCase) -> CaseResult:
    checklist = await _checklist_loader(case.payer, case.procedure, "")
    oracle = {c["text"]: case.expected_labels.get(c["id"], "met") for c in checklist}
    labels: dict[str, str] = {}
    for c in checklist:
        if c.get("kind") == "rule":
            labels[c["id"]] = _naive_decide(c.get("rule_spec") or {}, case)
        else:
            labels[c["id"]] = oracle.get(c["text"], "met")  # same judgment oracle
    # Clinician gap-fill (baseline also asks).
    for cid, status in list(labels.items()):
        if status == "unknown" and clinician_sim.answer(case, cid):
            labels[cid] = "met"
    # Uncited letter: one unsupported assertion per "met" criterion.
    lines = [
        {
            "text": f"The patient meets {c['text']}.",
            "fhir_refs": [],
            "requires_citation": _requires_citation(c),
        }
        for c in checklist
        if labels.get(c["id"]) == "met"
    ]
    return CaseResult(
        case_id=case.case_id,
        procedure=case.procedure,
        labels=labels,
        end_state=_end_state(labels),
        letter_lines=lines,
        known_refs=_known_refs(case),
    )
