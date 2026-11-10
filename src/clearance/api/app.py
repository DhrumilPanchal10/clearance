"""Clearance API (plan T7.1).

FastAPI surface over the in-process orchestration service: create and inspect
cases, stream live stage events over SSE, relay human decisions (coordinator /
manager / clinician) into the running case, and receive payer webhooks with
event-id dedupe. Role-based access uses :mod:`clearance.api.auth` (Clerk in
prod, dev headers offline).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from agentcore.auth import UserClaims
from clearance.api.auth import current_user
from clearance.api.deps import build_service
from clearance.api.schemas import (
    ClinicianAnswerRequest,
    CoordinatorDecisionRequest,
    CreateCaseRequest,
    PayerWebhookRequest,
)
from clearance.api.service import CaseService
from clearance.api.store import CaseRecord, CaseStore, EventBus

_MANAGER_ROLES = {"manager", "admin", "lead"}
_APPROVER_ROLES = {"coordinator", "manager", "admin", "lead"}
_CLINICIAN_ROLES = {"clinician", "manager", "admin", "lead"}


def get_service(request: Request) -> CaseService:
    svc: CaseService = request.app.state.service
    return svc


def _scoped(rec: CaseRecord, user: UserClaims) -> None:
    """Enforce clinic isolation: a user only sees their own tenant's cases."""
    if user.role not in {"admin"} and rec.tenant_id != user.tenant_id:
        raise HTTPException(status_code=404, detail="case not found")


def create_app(service: CaseService | None = None) -> FastAPI:
    app = FastAPI(title="Clearance API", version="1.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.service = service or build_service()

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/cases", status_code=201)
    async def create_case(
        body: CreateCaseRequest,
        user: UserClaims = Depends(current_user),
        svc: CaseService = Depends(get_service),
    ) -> dict[str, Any]:
        import uuid

        case_id = body.case_id or f"case-{uuid.uuid4().hex[:12]}"
        rec = await svc.create_case(
            {
                "case_id": case_id,
                "tenant_id": user.tenant_id,
                "patient_id": body.patient_id,
                "payer": body.payer,
                "procedure": body.procedure,
                "as_of": body.as_of,
            }
        )
        return rec.to_detail()

    @app.get("/cases")
    async def list_cases(
        user: UserClaims = Depends(current_user),
        svc: CaseService = Depends(get_service),
        stage: str | None = None,
        needs_manager: bool | None = None,
        mine_role: str | None = None,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for rec in svc_store(svc).list():
            if user.role != "admin" and rec.tenant_id != user.tenant_id:
                continue
            if stage and rec.stage != stage:
                continue
            if needs_manager is not None and rec.needs_manager != needs_manager:
                continue
            if mine_role == "manager" and not rec.needs_manager:
                continue
            if mine_role == "clinician" and rec.stage != "awaiting_clinician":
                continue
            rows.append(rec.to_summary())
        return {"cases": rows, "count": len(rows)}

    @app.get("/cases/{case_id}")
    async def get_case(
        case_id: str,
        user: UserClaims = Depends(current_user),
        svc: CaseService = Depends(get_service),
    ) -> dict[str, Any]:
        rec = svc_store(svc).get(case_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="case not found")
        _scoped(rec, user)
        detail = rec.to_detail()
        detail["timeline"] = [
            {
                "seq": e.seq,
                "at": e.at,
                "stage": e.stage,
                "kind": e.kind,
                "message": e.message,
                "data": e.data,
            }
            for e in svc_bus(svc).history(case_id)
        ]
        return detail

    @app.get("/cases/{case_id}/events")
    async def stream_events(
        case_id: str,
        svc: CaseService = Depends(get_service),
    ) -> StreamingResponse:
        rec = svc_store(svc).get(case_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="case not found")
        bus = svc_bus(svc)
        queue = bus.subscribe(case_id)

        async def gen() -> AsyncIterator[str]:
            try:
                while True:
                    try:
                        ev = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keep-alive\n\n"  # comment frame, keeps proxies open
                        continue
                    payload = {
                        "seq": ev.seq,
                        "at": ev.at,
                        "stage": ev.stage,
                        "kind": ev.kind,
                        "message": ev.message,
                        "data": ev.data,
                    }
                    yield f"event: {ev.kind}\ndata: {json.dumps(payload)}\n\n"
                    if ev.stage == "done" or ev.kind == "error":
                        yield "event: end\ndata: {}\n\n"
                        return
            finally:
                bus.unsubscribe(case_id, queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.post("/cases/{case_id}/decision")
    async def coordinator_decision(
        case_id: str,
        body: CoordinatorDecisionRequest,
        user: UserClaims = Depends(current_user),
        svc: CaseService = Depends(get_service),
    ) -> dict[str, Any]:
        rec = svc_store(svc).get(case_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="case not found")
        _scoped(rec, user)
        if user.role not in _APPROVER_ROLES:
            raise HTTPException(status_code=403, detail="role cannot approve")
        if rec.needs_manager and user.role not in _MANAGER_ROLES:
            raise HTTPException(status_code=403, detail="case requires a manager decision")
        if rec.stage != "awaiting_approval":
            raise HTTPException(status_code=409, detail=f"case is {rec.stage}, not awaiting_approval")
        svc.submit_coordinator_decision(case_id, body.decision, user.role, body.note)
        return {"ok": True, "decision": body.decision}

    @app.post("/cases/{case_id}/clinician")
    async def clinician_answer(
        case_id: str,
        body: ClinicianAnswerRequest,
        user: UserClaims = Depends(current_user),
        svc: CaseService = Depends(get_service),
    ) -> dict[str, Any]:
        rec = svc_store(svc).get(case_id)
        if rec is None:
            raise HTTPException(status_code=404, detail="case not found")
        _scoped(rec, user)
        if user.role not in _CLINICIAN_ROLES:
            raise HTTPException(status_code=403, detail="role cannot answer clinical gaps")
        if rec.stage != "awaiting_clinician":
            raise HTTPException(status_code=409, detail=f"case is {rec.stage}")
        svc.submit_clinician_answers(case_id, body.answers)
        return {"ok": True}

    @app.post("/webhooks/payer")
    async def payer_webhook(
        body: PayerWebhookRequest,
        svc: CaseService = Depends(get_service),
    ) -> dict[str, Any]:
        accepted = svc.payer_webhook(
            body.case_id,
            body.event_id,
            {"status": body.status, "denial_reason": body.denial_reason},
        )
        return {"ok": True, "accepted": accepted}

    @app.get("/playbook")
    async def playbook(
        user: UserClaims = Depends(current_user),
        svc: CaseService = Depends(get_service),
    ) -> dict[str, Any]:
        from dataclasses import asdict

        notes = svc.memory.consolidate()
        return {"notes": [asdict(n) for n in notes]}

    return app


# Small accessors keep handlers readable.
def svc_store(svc: CaseService) -> CaseStore:
    return svc.store


def svc_bus(svc: CaseService) -> EventBus:
    return svc.bus
