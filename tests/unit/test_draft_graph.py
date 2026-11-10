"""Tests for submission (T5.5), verifier (T5.6), and the draft sub-graph (T5.8)."""

from __future__ import annotations

from typing import Any

from clearance.agents.graphs import build_draft_graph
from clearance.agents.state import CriterionDecision, new_case_state
from clearance.agents.submission import make_submission_node
from clearance.agents.verifier import make_verifier_node

CHECKLIST = [
    {"id": "c1", "text": "Red-flag condition present.", "kind": "judgment", "rule_spec": None},
    {"id": "c2", "text": "4 weeks conservative therapy.", "kind": "rule", "rule_spec": {}},
]


def _state(decisions: list[CriterionDecision]) -> dict[str, Any]:
    st = new_case_state(
        case_id="case-1",
        tenant_id="clinic-a",
        patient_id="pat-1",
        payer="medicare",
        procedure="lumbar_spine_mri",
        as_of="2020-12-01",
    )
    st["checklist"] = CHECKLIST  # type: ignore[typeddict-item]
    st["decisions"] = decisions
    return dict(st)


async def test_submission_builds_cited_letter() -> None:
    node = make_submission_node()
    out = await node(
        _state(
            [
                CriterionDecision(
                    criterion_id="c1", status="met", evidence_refs=["cond-1"], method="agent"
                ),
                CriterionDecision(
                    criterion_id="c2", status="met", evidence_refs=["proc-1"], method="rule"
                ),
            ]
        )
    )
    lines = out["letter"]["sections"][0]["lines"]
    assert len(lines) == 2
    assert {ref for line in lines for ref in line["fhir_refs"]} == {"cond-1", "proc-1"}
    assert out["packet"]["procedure"] == "lumbar_spine_mri"


async def test_draft_graph_passes_when_all_met_and_cited() -> None:
    graph = build_draft_graph(make_submission_node(), make_verifier_node())
    result = await graph.ainvoke(
        _state(
            [
                CriterionDecision(
                    criterion_id="c1", status="met", evidence_refs=["cond-1"], method="agent"
                ),
                CriterionDecision(
                    criterion_id="c2", status="met", evidence_refs=["proc-1"], method="rule"
                ),
            ]
        )
    )
    assert result["verdict"] == "pass"


async def test_draft_graph_escalates_on_unmet_criterion() -> None:
    graph = build_draft_graph(make_submission_node(), make_verifier_node())
    result = await graph.ainvoke(
        _state(
            [
                CriterionDecision(
                    criterion_id="c1", status="met", evidence_refs=["cond-1"], method="agent"
                ),
                CriterionDecision(criterion_id="c2", status="not_met", method="rule"),
            ]
        )
    )
    assert result["verdict"] == "escalate"


async def test_draft_graph_revises_then_escalates_on_uncited_claim() -> None:
    graph = build_draft_graph(make_submission_node(), make_verifier_node())
    # Judgment criterion 'met' with no evidence refs -> uncited clinical line.
    result = await graph.ainvoke(
        _state(
            [CriterionDecision(criterion_id="c1", status="met", evidence_refs=[], method="agent")]
        )
    )
    # Deterministic submission can't fix it, so after the revision budget it escalates.
    assert result["verdict"] == "escalate"
    assert result["revision_count"] == 2
