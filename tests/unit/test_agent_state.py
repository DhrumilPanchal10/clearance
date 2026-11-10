"""Tests for agent state schemas + reducers (T5.1)."""

from __future__ import annotations

from clearance.agents.state import (
    CriterionDecision,
    EvidenceCard,
    all_met,
    merge_cards,
    merge_decisions,
    new_case_state,
)


def test_new_case_state_defaults() -> None:
    st = new_case_state(
        case_id="c1",
        tenant_id="clinic-a",
        patient_id="pat-1",
        payer="medicare",
        procedure="lumbar_spine_mri",
        as_of="2020-01-01",
    )
    assert st["decisions"] == [] and st["evidence_cards"] == [] and st["errors"] == []


def test_merge_decisions_last_write_wins_by_criterion() -> None:
    left = [CriterionDecision(criterion_id="c1", status="unknown")]
    right = [
        CriterionDecision(criterion_id="c1", status="met"),  # overrides c1
        CriterionDecision(criterion_id="c2", status="not_met"),
    ]
    merged = {d.criterion_id: d for d in merge_decisions(left, right)}
    assert merged["c1"].status == "met"
    assert merged["c2"].status == "not_met"
    assert len(merged) == 2


def test_merge_cards_dedupes_by_criterion() -> None:
    left = [EvidenceCard(criterion_id="c1", summary="old")]
    right = [EvidenceCard(criterion_id="c1", summary="new")]
    merged = merge_cards(left, right)
    assert len(merged) == 1 and merged[0].summary == "new"


def test_all_met() -> None:
    assert not all_met({"decisions": []})
    assert all_met({"decisions": [CriterionDecision(criterion_id="c1", status="met")]})
    assert not all_met(
        {
            "decisions": [
                CriterionDecision(criterion_id="c1", status="met"),
                CriterionDecision(criterion_id="c2", status="not_met"),
            ]
        }
    )
