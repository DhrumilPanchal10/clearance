"""Demo backend (``uvicorn clearance.api.demo:app``).

A fully self-contained Clearance API: real ground-truth checklists drive the
criteria, but assessment, drafting, the payer, and outcomes are synthesised
deterministically from the patient id — so the entire UI is clickable with **no
Postgres, payer service, Temporal, or LLM**. Outcomes vary across cases
(approve / clinician-gap / manager-escalation / denial→appeal) so every screen
has something real to show.

This is the demo/offline backend. Production wiring lives in
:func:`clearance.api.deps.build_production_deps`.
"""

from __future__ import annotations

import hashlib
from typing import Any

from clearance.agents.supervisor import make_checklist_loader
from clearance.api.app import create_app
from clearance.api.service import CaseService, Deps
from clearance.api.store import CaseStore, EventBus
from clearance.memory.episodic import EpisodicMemory

_checklists = make_checklist_loader()


def _seed(case_id: str) -> int:
    return int(hashlib.sha256(case_id.encode()).hexdigest(), 16)


async def _assess(inp: dict[str, Any]) -> dict[str, Any]:
    procedure = inp["procedure"]
    checklist = await _checklists(inp["payer"], procedure, "")
    seed = _seed(inp["patient_id"] + procedure)
    decisions: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    for i, c in enumerate(checklist):
        is_rule = c.get("kind") == "rule"
        # One in ~5 agent criteria comes back unknown to exercise the gap-fill.
        unknown = (not is_rule) and (seed >> (i + 1)) % 5 == 0
        status = "unknown" if unknown else "met"
        conf = 1.0 if is_rule else (0.68 if (seed >> i) % 4 == 0 else 0.93)
        ref = f"{_fhir_type(c)}/{(seed >> (i * 2)) % 9000 + 1000}"
        decisions.append(
            {
                "criterion_id": c["id"],
                "status": status,
                "evidence_refs": [] if unknown else [ref],
                "confidence": conf,
                "method": "rule" if is_rule else "agent",
                "rationale": "" if is_rule else _rationale(c, status),
            }
        )
        evidence.append(
            {
                "criterion_id": c["id"],
                "summary": _evidence_summary(c, status),
                "fhir_refs": [] if unknown else [ref],
            }
        )
    return {
        "policy_version": _policy_version(procedure),
        "checklist": checklist,
        "decisions": decisions,
        "evidence_cards": evidence,
        "errors": [],
    }


async def _draft(state: dict[str, Any]) -> dict[str, Any]:
    checklist = {c["id"]: c for c in state.get("checklist", [])}
    lines = []
    for d in state.get("decisions", []):
        if d.get("status") != "met":
            continue
        c = checklist.get(d["criterion_id"], {})
        lines.append(
            {
                "text": f"The patient meets the criterion: {c.get('text', d['criterion_id'])}.",
                "fhir_refs": d.get("evidence_refs", []),
            }
        )
    hint = state.get("playbook_hint")
    letter = {
        "title": f"Letter of Medical Necessity — {state['procedure']}",
        "sections": [
            {
                "heading": "Clinical justification",
                "lines": lines
                or [{"text": "Supporting clinical evidence is documented.", "fhir_refs": []}],
            }
        ]
        + (
            [{"heading": "Payer-specific note", "lines": [{"text": hint, "fhir_refs": []}]}]
            if hint
            else []
        ),
    }
    return {"verdict": "pass", "letter": letter, "packet": {"case_id": state["case_id"]}}


async def _submit(args: dict[str, Any]) -> dict[str, Any]:
    seed = _seed(args["case_id"])
    attempt = args.get("attempt", 1)
    bucket = seed % 10
    if bucket < 6 or attempt >= 2:  # most approve; appeals tend to succeed
        return {"claim_id": f"PA-{seed % 100000}", "status": "approved", "denial_reason": None}
    if bucket < 8:
        return {"claim_id": f"PA-{seed % 100000}", "status": "pended", "denial_reason": None}
    return {
        "claim_id": f"PA-{seed % 100000}",
        "status": "denied",
        "denial_reason": "insufficient_documentation",
    }


async def _appeal(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "appeal": {
            "kind": "appeal",
            "rebuttal": f"Additional documentation addresses: {state.get('denial_reason')}.",
        }
    }


def _fhir_type(c: dict[str, Any]) -> str:
    text = (c.get("text") or "").lower()
    if "age" in text:
        return "Patient"
    if "therapy" in text or "conservative" in text:
        return "Procedure"
    if "pregnan" in text:
        return "Observation"
    return "Condition"


def _policy_version(procedure: str) -> str:
    return {
        "lumbar_spine_mri": "L34220",
        "knee_mri": "NCD-220.2",
        "ct_abdomen": "L34415",
    }.get(procedure, "—")


def _rationale(c: dict[str, Any], status: str) -> str:
    if status == "unknown":
        return "Not determinable from structured chart data; clinician confirmation requested."
    return "Chart notes support this criterion; cited to the referenced resource."


def _evidence_summary(c: dict[str, Any], status: str) -> str:
    if status == "unknown":
        return "No structured evidence found in the chart for this criterion."
    return f"Documented in the patient chart: {c.get('text', '')}."


def build_demo_service() -> CaseService:
    deps = Deps(
        assess=_assess,
        draft=_draft,
        submit=_submit,
        appeal=_appeal,
        memory=EpisodicMemory(),
    )
    return CaseService(deps, CaseStore(), EventBus())


_SEED_CASES = [
    ("patient-00017", "lumbar_spine_mri"),
    ("patient-00042", "knee_mri"),
    ("patient-00088", "ct_abdomen"),
    ("patient-00103", "lumbar_spine_mri"),
    ("patient-00129", "knee_mri"),
    ("patient-00155", "ct_abdomen"),
    ("patient-00204", "lumbar_spine_mri"),
]

_service = build_demo_service()
app = create_app(service=_service)


@app.on_event("startup")
async def _seed_demo_cases() -> None:  # pragma: no cover - demo convenience
    for i, (patient, procedure) in enumerate(_SEED_CASES):
        await _service.create_case(
            {
                "case_id": f"demo-{i:02d}-{patient[-5:]}",
                "tenant_id": "clinic-a",
                "patient_id": patient,
                "payer": "medicare",
                "procedure": procedure,
                "as_of": "2020-12-01",
            }
        )
