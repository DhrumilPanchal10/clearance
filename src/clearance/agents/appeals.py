"""Appeals node (plan T5.7): denial reason -> implicated criteria -> evidence
-> appeal draft.

Maps the payer's denial reason code to the criteria it implicates, then
assembles a cited rebuttal from the decisions/evidence already gathered.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentcore.guardrails import guarded
from clearance.agents.state import CriterionDecision
from clearance.mcp_servers.documents import LetterDraft, LetterLine, LetterSection

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _targets(
    reason: str | None,
    decisions: list[CriterionDecision],
    checklist: list[dict[str, Any]],
) -> list[CriterionDecision]:
    by_id = {c["id"]: c for c in checklist}

    def is_conservative(d: CriterionDecision) -> bool:
        spec = (by_id.get(d.criterion_id, {}) or {}).get("rule_spec") or {}
        return spec.get("kind") == "conservative_therapy"

    if reason == "no_conservative_therapy":
        hits = [d for d in decisions if is_conservative(d)]
    elif reason == "missing_documentation":
        hits = [d for d in decisions if not d.evidence_refs]
    elif reason in {"criteria_not_met", "not_medically_necessary"}:
        hits = [d for d in decisions if d.status != "met"]
    else:
        hits = list(decisions)
    return hits or list(decisions)


def make_appeals_node() -> NodeFn:
    @guarded("appeals")
    async def appeals(state: dict[str, Any]) -> dict[str, Any]:
        reason = state.get("denial_reason")
        decisions = state.get("decisions", [])
        checklist = state.get("checklist", [])
        by_id = {c["id"]: c for c in checklist}

        lines: list[LetterLine] = []
        for d in _targets(reason, decisions, checklist):
            crit = by_id.get(d.criterion_id, {})
            text = crit.get("text") or d.criterion_id
            if d.status == "met":
                body = f"This criterion is met: {text}"
            else:
                body = f"We request reconsideration of: {text} ({d.rationale})"
            lines.append(LetterLine(text=body, fhir_refs=list(d.evidence_refs)))

        draft = LetterDraft(
            kind="appeal",
            title=f"Appeal of Prior-Authorization Denial ({reason or 'unspecified'})",
            payer=state.get("payer", ""),
            procedure=state.get("procedure", ""),
            patient_ref=f"Patient/{state.get('patient_id', '')}",
            sections=[LetterSection(heading="Grounds for appeal", lines=lines)],
        )
        return {"appeal": draft.model_dump()}

    return appeals
