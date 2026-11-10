"""Evidence node (plan T5.3): build a per-criterion EvidenceCard from the chart.

Runs in parallel with the policy node. For rule criteria it links the FHIR
resources whose codes match the rule's code set; for judgment criteria it
summarizes the relevant chart slice for the criteria agent to reason over.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentcore.guardrails import guarded
from clearance.agents.policy import ChecklistLoader
from clearance.agents.state import EvidenceCard, service_context

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _spec_codes(rule_spec: dict[str, Any] | None) -> set[str]:
    if not rule_spec:
        return set()
    codes = rule_spec.get("codes") or rule_spec.get("any_of") or []
    return set(codes)


def _matching_refs(facts: dict[str, Any], codes: set[str], *buckets: str) -> list[str]:
    refs: list[str] = []
    for bucket in buckets:
        for item in facts.get(bucket, []) or []:
            if codes & set(item.get("codes", [])):
                refs.append(item["id"])
    return refs


def _card_for(criterion: dict[str, Any], facts: dict[str, Any]) -> EvidenceCard:
    cid = criterion["id"]
    if criterion.get("kind") == "rule":
        spec = criterion.get("rule_spec") or {}
        kind = spec.get("kind")
        codes = _spec_codes(spec)
        if kind == "diagnosis":
            refs = _matching_refs(facts, codes, "conditions")
        elif kind == "prior_procedure":
            refs = _matching_refs(facts, codes, "procedures")
        elif kind == "conservative_therapy":
            refs = _matching_refs(facts, codes, "procedures", "medications")
        else:  # age or other — demographic, no resource refs
            refs = []
        summary = f"{len(refs)} matching resource(s) for rule '{kind}'."
        return EvidenceCard(criterion_id=cid, summary=summary, fhir_refs=refs)

    # Judgment criterion: summarize the chart slice for the agent.
    counts = {b: len(facts.get(b, []) or []) for b in ("conditions", "procedures", "medications")}
    summary = "Chart context — " + ", ".join(f"{k}: {v}" for k, v in counts.items())
    return EvidenceCard(criterion_id=cid, summary=summary, fhir_refs=[])


def make_evidence_node(fhir_tools: Any, load_checklist: ChecklistLoader) -> NodeFn:
    @guarded("evidence")
    async def evidence(state: dict[str, Any]) -> dict[str, Any]:
        ctx = service_context(state)
        facts = await fhir_tools.get_patient_facts(ctx, patient_id=state["patient_id"])
        criteria = await load_checklist(
            state["payer"], state["procedure"], state.get("policy_version") or ""
        )
        cards = [_card_for(c, facts) for c in criteria]
        return {"evidence_cards": cards}

    return evidence
