"""Case state + decision schemas for the LangGraph agents (plan T5.1).

The graph state is a TypedDict with reducers so the parallel evidence ∥ policy
branches can write concurrently without clobbering each other. Per-criterion
results are keyed by ``criterion_id`` and merged last-write-wins.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

from agentcore.auth import UserClaims
from clearance.mcp_servers.base import ToolContext

DecisionStatus = Literal["met", "not_met", "unknown"]
DecisionMethod = Literal["rule", "agent"]


class EvidenceCard(BaseModel):
    """Evidence gathered for one criterion (enriched in T2.2)."""

    criterion_id: str
    summary: str
    fhir_refs: list[str] = Field(default_factory=list)


class CriterionDecision(BaseModel):
    """Whether one criterion is met, how it was decided, and on what evidence."""

    criterion_id: str
    status: DecisionStatus
    evidence_refs: list[str] = Field(default_factory=list)
    confidence: float = 1.0
    method: DecisionMethod = "rule"
    rationale: str = ""


def _merge_by_criterion(left: list[BaseModel], right: list[BaseModel]) -> list[BaseModel]:
    """Reducer: merge two lists keyed by ``criterion_id``, last write wins."""
    merged: dict[str, BaseModel] = {m.criterion_id: m for m in left}  # type: ignore[attr-defined]
    for m in right:
        merged[m.criterion_id] = m  # type: ignore[attr-defined]
    return list(merged.values())


def merge_cards(left: list[EvidenceCard], right: list[EvidenceCard]) -> list[EvidenceCard]:
    return _merge_by_criterion(left, right)  # type: ignore[arg-type,return-value]


def merge_decisions(
    left: list[CriterionDecision], right: list[CriterionDecision]
) -> list[CriterionDecision]:
    return _merge_by_criterion(left, right)  # type: ignore[arg-type,return-value]


class CaseState(TypedDict, total=False):
    """LangGraph state for one prior-auth case stage."""

    # Identity / inputs
    case_id: str
    tenant_id: str  # clinic_id, read by guarded() for span scoping
    patient_id: str
    payer: str
    procedure: str
    as_of: str  # ISO date the policy/evidence are evaluated against

    # Intake output
    policy_version: str | None

    # Parallel branch outputs (reducers merge concurrent writes)
    checklist: list[dict[str, Any]]  # Criterion dicts from the policy agent
    evidence_cards: Annotated[list[EvidenceCard], merge_cards]

    # Criteria decision output
    decisions: Annotated[list[CriterionDecision], merge_decisions]

    # Draft / verify
    letter: dict[str, Any]  # LetterDraft dict
    packet: dict[str, Any]
    verdict: str  # pass | revise | escalate
    revision_count: int

    # Appeal
    denial_reason: str | None
    appeal: dict[str, Any]

    # Cross-cutting (read by guarded())
    run_cost: Any
    errors: Annotated[list[str], operator.add]
    degraded: bool


def new_case_state(
    *,
    case_id: str,
    tenant_id: str,
    patient_id: str,
    payer: str,
    procedure: str,
    as_of: str,
) -> CaseState:
    return CaseState(
        case_id=case_id,
        tenant_id=tenant_id,
        patient_id=patient_id,
        payer=payer,
        procedure=procedure,
        as_of=as_of,
        checklist=[],
        evidence_cards=[],
        decisions=[],
        revision_count=0,
        errors=[],
    )


def service_context(state: dict[str, Any], role: str = "coordinator") -> ToolContext:
    """Tool-call identity the agents act under — scoped to the case's clinic."""
    clinic = state.get("tenant_id", "")
    return ToolContext(
        claims=UserClaims(user_id="agent", tenant_id=clinic, role=role, raw={}),
        clinic_id=clinic,
    )


def decided_criteria(state: CaseState) -> set[str]:
    return {d.criterion_id for d in state.get("decisions", [])}


def all_met(state: CaseState) -> bool:
    decisions = state.get("decisions", [])
    return bool(decisions) and all(d.status == "met" for d in decisions)
