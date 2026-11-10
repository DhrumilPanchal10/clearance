"""Tests for the appeals node + appeal sub-graph (T5.7, T5.8)."""

from __future__ import annotations

from typing import Any

from clearance.agents.appeals import make_appeals_node
from clearance.agents.graphs import build_appeal_graph
from clearance.agents.state import CriterionDecision, new_case_state

CHECKLIST = [
    {
        "id": "c2",
        "text": "4 weeks conservative therapy.",
        "kind": "rule",
        "rule_spec": {"kind": "conservative_therapy", "codes": ["97110"], "min_duration_days": 28},
    },
    {"id": "c1", "text": "Red-flag present.", "kind": "judgment", "rule_spec": None},
]


def _state(reason: str, decisions: list[CriterionDecision]) -> dict[str, Any]:
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
    st["denial_reason"] = reason
    return dict(st)


async def test_appeal_targets_conservative_therapy_reason() -> None:
    graph = build_appeal_graph(make_appeals_node())
    result = await graph.ainvoke(
        _state(
            "no_conservative_therapy",
            [
                CriterionDecision(
                    criterion_id="c2", status="met", evidence_refs=["proc-1"], method="rule"
                ),
                CriterionDecision(
                    criterion_id="c1", status="met", evidence_refs=["cond-1"], method="agent"
                ),
            ],
        )
    )
    appeal = result["appeal"]
    assert appeal["kind"] == "appeal"
    lines = appeal["sections"][0]["lines"]
    # Only the conservative-therapy criterion (c2) is targeted, citing its evidence.
    assert len(lines) == 1
    assert lines[0]["fhir_refs"] == ["proc-1"]
    assert "no_conservative_therapy" in appeal["title"]


async def test_appeal_targets_unmet_for_criteria_not_met() -> None:
    node = make_appeals_node()
    out = await node(
        _state(
            "criteria_not_met",
            [
                CriterionDecision(
                    criterion_id="c2", status="not_met", method="rule", rationale="17d < 28d"
                ),
                CriterionDecision(
                    criterion_id="c1", status="met", evidence_refs=["cond-1"], method="agent"
                ),
            ],
        )
    )
    lines = out["appeal"]["sections"][0]["lines"]
    assert len(lines) == 1
    assert "reconsideration" in lines[0]["text"]
