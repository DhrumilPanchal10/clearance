"""Submission node (plan T5.5): assemble the packet + letter of medical necessity.

Deterministic assembly: one clinical line per MET criterion, carrying that
criterion's FHIR evidence refs. Citations are therefore guaranteed by
construction for rule-met criteria; a judgment-met criterion with no evidence
produces an uncited line that the verifier (T5.6) will catch.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentcore.guardrails import guarded
from clearance.mcp_servers.documents import LetterDraft, LetterLine, LetterSection

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def _build_letter(state: dict[str, Any]) -> LetterDraft:
    by_id = {c["id"]: c for c in state.get("checklist", [])}
    lines: list[LetterLine] = []
    for d in state.get("decisions", []):
        if d.status != "met":
            continue
        crit = by_id.get(d.criterion_id, {})
        text = crit.get("text") or d.rationale or d.criterion_id
        lines.append(LetterLine(text=text, fhir_refs=list(d.evidence_refs)))
    return LetterDraft(
        kind="letter_of_medical_necessity",
        title="Letter of Medical Necessity",
        payer=state.get("payer", ""),
        procedure=state.get("procedure", ""),
        patient_ref=f"Patient/{state.get('patient_id', '')}",
        sections=[LetterSection(heading="Clinical criteria met", lines=lines)],
    )


def make_submission_node() -> NodeFn:
    @guarded("submission")
    async def submission(state: dict[str, Any]) -> dict[str, Any]:
        # Increment only on re-entry (a prior letter exists) so the first pass is 0.
        revision_count = state.get("revision_count", 0) + (1 if state.get("letter") else 0)
        letter = _build_letter(state)
        packet = {
            "case_id": state.get("case_id"),
            "patient_ref": f"Patient/{state.get('patient_id', '')}",
            "payer": state.get("payer"),
            "procedure": state.get("procedure"),
            "policy_version": state.get("policy_version"),
            "criteria": [
                {
                    "id": d.criterion_id,
                    "status": d.status,
                    "method": d.method,
                    "evidence_refs": d.evidence_refs,
                }
                for d in state.get("decisions", [])
            ],
        }
        return {"letter": letter.model_dump(), "packet": packet, "revision_count": revision_count}

    return submission
