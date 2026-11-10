"""Criteria-decision node (plan T5.4).

Rule criteria are decided in Python by the T1.4 engine (never a model); only
judgment criteria go to an LLM. Each decision records its method, confidence and
the FHIR evidence it relied on.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any

from pydantic import BaseModel, Field

from agentcore.guardrails import guarded
from agentcore.llm import complete
from clearance.agents.state import CriterionDecision, DecisionStatus, EvidenceCard, service_context
from clearance.policies.rules import PatientFacts, evaluate, parse_rule_spec

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


class _JudgeResult(BaseModel):
    status: DecisionStatus
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: str = ""


def _reshape(
    items: list[dict[str, Any]], rtype: str, code_key: str, date_key: str
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in items:
        resource: dict[str, Any] = {
            "resourceType": rtype,
            "id": i["id"],
            code_key: {"coding": [{"code": c} for c in i.get("codes", [])]},
        }
        if i.get("date"):
            resource[date_key] = i["date"]
        out.append(resource)
    return out


def _to_patient_facts(raw: dict[str, Any], as_of: str) -> PatientFacts:
    bd = raw.get("birth_date")
    return PatientFacts(
        as_of=date.fromisoformat(as_of),
        birth_date=date.fromisoformat(bd) if bd else None,
        conditions=_reshape(raw.get("conditions", []), "Condition", "code", "onsetDateTime"),
        procedures=_reshape(raw.get("procedures", []), "Procedure", "code", "performedDateTime"),
        medications=_reshape(
            raw.get("medications", []),
            "MedicationRequest",
            "medicationCodeableConcept",
            "authoredOn",
        ),
    )


_JUDGE_SYSTEM = (
    "You decide whether a single prior-authorization criterion is met for a patient, "
    "using ONLY the supplied evidence summary. Answer met, not_met, or unknown (use "
    "unknown when the evidence is insufficient). Give a calibrated confidence and a "
    "one-sentence rationale. Do not invent facts beyond the evidence."
)


async def _judge(
    criterion: dict[str, Any], card: EvidenceCard | None, run_cost: Any
) -> CriterionDecision:
    summary = card.summary if card else "No evidence gathered."
    messages = [
        {"role": "system", "content": _JUDGE_SYSTEM},
        {"role": "user", "content": f"Criterion: {criterion['text']}\n\nEvidence: {summary}"},
    ]
    result: _JudgeResult = await complete(
        messages, schema=_JudgeResult, model_tier="strong", run_cost=run_cost
    )
    return CriterionDecision(
        criterion_id=criterion["id"],
        status=result.status,
        evidence_refs=card.fhir_refs if card else [],
        confidence=result.confidence,
        method="agent",
        rationale=result.rationale,
    )


def make_criteria_node(fhir_tools: Any) -> NodeFn:
    @guarded("criteria")
    async def criteria(state: dict[str, Any]) -> dict[str, Any]:
        ctx = service_context(state)
        raw = await fhir_tools.get_patient_facts(ctx, patient_id=state["patient_id"])
        facts = _to_patient_facts(raw, state["as_of"])
        cards = {c.criterion_id: c for c in state.get("evidence_cards", [])}

        decisions: list[CriterionDecision] = []
        for crit in state.get("checklist", []):
            if crit.get("kind") == "rule":
                res = evaluate(parse_rule_spec(crit["rule_spec"]), facts)
                decisions.append(
                    CriterionDecision(
                        criterion_id=crit["id"],
                        status=res.status,
                        evidence_refs=res.evidence_refs,
                        confidence=1.0,
                        method="rule",
                        rationale=res.detail,
                    )
                )
            else:
                decisions.append(await _judge(crit, cards.get(crit["id"]), state.get("run_cost")))
        return {"decisions": decisions}

    return criteria
