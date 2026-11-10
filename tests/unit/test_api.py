"""API + orchestration-service tests (plan T7.1/T7.2/T7.4).

Fake assess/draft/submit/appeal adapters stand in for the LangGraph sub-graphs
and the payer, so the whole case lifecycle — create, assess, HITL gates,
submit, track, appeal, SSE timeline, webhook dedupe, manager routing, episodic
memory — runs with no DB, payer, or LLM.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from clearance.api.app import create_app
from clearance.api.service import CaseService, Deps
from clearance.api.store import CaseStore, EventBus
from clearance.memory.episodic import EpisodicMemory

COORD = {"X-Role": "coordinator", "X-Tenant": "clinic-a"}
MGR = {"X-Role": "manager", "X-Tenant": "clinic-a"}
CLIN = {"X-Role": "clinician", "X-Tenant": "clinic-a"}


def _decisions(status: str = "met", method: str = "rule", conf: float = 1.0) -> list[dict[str, Any]]:
    return [
        {"criterion_id": "c1", "status": status, "evidence_refs": ["r1"], "method": method,
         "confidence": conf, "rationale": ""},
    ]


def make_deps(
    tmp: Path,
    *,
    decisions: list[dict[str, Any]] | None = None,
    submit_status: str = "approved",
    denial_reason: str | None = None,
) -> Deps:
    decisions = decisions if decisions is not None else _decisions()

    async def assess(inp: dict[str, Any]) -> dict[str, Any]:
        return {
            "policy_version": "L34220",
            "checklist": [{"id": "c1", "text": "Conservative therapy ≥28 days", "kind": "rule"}],
            "decisions": [dict(d) for d in decisions],
            "evidence_cards": [{"criterion_id": "c1", "summary": "PT notes", "fhir_refs": ["r1"]}],
            "errors": [],
        }

    async def draft(state: dict[str, Any]) -> dict[str, Any]:
        return {"verdict": "pass", "letter": {"title": "LMN"}, "packet": {"case_id": state["case_id"]}}

    async def submit(args: dict[str, Any]) -> dict[str, Any]:
        return {"claim_id": "PA-1", "status": submit_status, "denial_reason": denial_reason}

    async def appeal(state: dict[str, Any]) -> dict[str, Any]:
        return {"appeal": {"kind": "appeal"}}

    return Deps(
        assess=assess,
        draft=draft,
        submit=submit,
        appeal=appeal,
        memory=EpisodicMemory(tmp / "episodes.jsonl", tmp / "playbook.json"),
    )


def make_service(deps: Deps) -> CaseService:
    return CaseService(deps, CaseStore(), EventBus())


def client_for(svc: CaseService) -> httpx.AsyncClient:
    app = create_app(service=svc)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def _create(c: httpx.AsyncClient, headers: dict[str, str] = COORD) -> str:
    resp = await c.post(
        "/cases",
        headers=headers,
        json={"patient_id": "pat-1", "payer": "medicare",
              "procedure": "lumbar_spine_mri", "as_of": "2020-12-01"},
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["case_id"]


async def test_happy_path_approved(tmp_path: Path) -> None:
    svc = make_service(make_deps(tmp_path))
    async with client_for(svc) as c:
        case_id = await _create(c)
        await svc.wait_until_idle(case_id)
        detail = (await c.get(f"/cases/{case_id}", headers=COORD)).json()
        assert detail["stage"] == "awaiting_approval"
        assert detail["assigned_role"] == "coordinator"

        r = await c.post(f"/cases/{case_id}/decision", headers=COORD, json={"decision": "approve"})
        assert r.status_code == 200
        await svc.wait_until_idle(case_id)
        detail = (await c.get(f"/cases/{case_id}", headers=COORD)).json()
        assert detail["outcome"] == "approved"
        assert any(e["stage"] == "done" for e in detail["timeline"])
    await svc.aclose()


async def test_reject_path(tmp_path: Path) -> None:
    svc = make_service(make_deps(tmp_path))
    async with client_for(svc) as c:
        case_id = await _create(c)
        await svc.wait_until_idle(case_id)
        await c.post(f"/cases/{case_id}/decision", headers=COORD, json={"decision": "reject"})
        await svc.wait_until_idle(case_id)
        detail = (await c.get(f"/cases/{case_id}", headers=COORD)).json()
        assert detail["outcome"] == "rejected"
    await svc.aclose()


async def test_low_confidence_routes_to_manager(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, decisions=_decisions(method="agent", conf=0.5))
    svc = make_service(deps)
    async with client_for(svc) as c:
        case_id = await _create(c)
        await svc.wait_until_idle(case_id)
        detail = (await c.get(f"/cases/{case_id}", headers=MGR)).json()
        assert detail["needs_manager"] is True
        assert "low_confidence" in detail["manager_reasons"]
        # A coordinator may not decide a manager-queued case.
        r = await c.post(f"/cases/{case_id}/decision", headers=COORD, json={"decision": "approve"})
        assert r.status_code == 403
        # The manager can.
        r = await c.post(f"/cases/{case_id}/decision", headers=MGR, json={"decision": "approve"})
        assert r.status_code == 200
        await svc.wait_until_idle(case_id)
        assert svc.store.get(case_id).outcome == "approved"
    await svc.aclose()


async def test_clinician_gap_fill(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, decisions=_decisions(status="unknown", method="agent"))
    svc = make_service(deps)
    async with client_for(svc) as c:
        case_id = await _create(c)
        await svc.wait_until_idle(case_id)
        detail = (await c.get(f"/cases/{case_id}", headers=CLIN)).json()
        assert detail["stage"] == "awaiting_clinician"
        assert detail["clinician_questions"]
        r = await c.post(f"/cases/{case_id}/clinician", headers=CLIN, json={"answers": {"c1": "yes"}})
        assert r.status_code == 200
        await svc.wait_until_idle(case_id)
        # After the answer the case advances to approval.
        assert svc.store.get(case_id).stage == "awaiting_approval"
    await svc.aclose()


async def test_denial_then_appeal_then_deny(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, submit_status="denied", denial_reason="criteria_not_met")
    svc = make_service(deps)
    async with client_for(svc) as c:
        case_id = await _create(c)
        # Approve each time it parks at approval, until terminal.
        for _ in range(10):
            await svc.wait_until_idle(case_id)
            rec = svc.store.get(case_id)
            if rec.outcome:
                break
            if rec.stage == "awaiting_approval":
                await c.post(f"/cases/{case_id}/decision", headers=MGR, json={"decision": "approve"})
        rec = svc.store.get(case_id)
        assert rec.outcome == "denied"
        assert rec.appeal_cycles == 2
    # Episodic memory recorded the terminal denial.
    episodes = deps.memory.load_episodes()
    assert episodes and episodes[-1].outcome == "denied"
    assert episodes[-1].denial_reason == "criteria_not_met"
    await svc.aclose()


async def test_pended_then_webhook_approves(tmp_path: Path) -> None:
    deps = make_deps(tmp_path, submit_status="pended")
    svc = make_service(deps)
    async with client_for(svc) as c:
        case_id = await _create(c)
        await svc.wait_until_idle(case_id)
        await c.post(f"/cases/{case_id}/decision", headers=COORD, json={"decision": "approve"})
        await svc.wait_until_idle(case_id)  # now tracking, parked on payer webhook
        assert svc.store.get(case_id).stage == "tracking"
        # Duplicate event id is ignored; first delivery wins.
        first = await c.post("/webhooks/payer", json={
            "event_id": "evt-1", "case_id": case_id, "status": "approved"})
        assert first.json()["accepted"] is True
        dup = await c.post("/webhooks/payer", json={
            "event_id": "evt-1", "case_id": case_id, "status": "denied"})
        assert dup.json()["accepted"] is False
        await svc.wait_until_idle(case_id)
        assert svc.store.get(case_id).outcome == "approved"
    await svc.aclose()


async def test_tenant_isolation(tmp_path: Path) -> None:
    svc = make_service(make_deps(tmp_path))
    async with client_for(svc) as c:
        case_id = await _create(c, headers=COORD)
        other = {"X-Role": "coordinator", "X-Tenant": "clinic-b"}
        r = await c.get(f"/cases/{case_id}", headers=other)
        assert r.status_code == 404
    await svc.aclose()


async def test_unknown_role_rejected(tmp_path: Path) -> None:
    svc = make_service(make_deps(tmp_path))
    async with client_for(svc) as c:
        r = await c.post("/cases", headers={"X-Role": "wizard"},
                         json={"patient_id": "p", "payer": "medicare",
                               "procedure": "knee_mri", "as_of": "2020-01-01"})
        assert r.status_code == 403
    await svc.aclose()
