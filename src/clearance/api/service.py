"""Case orchestration service (plan T7.1 + T7.2 + T7.4).

Drives one prior-auth case through the same state machine as the Temporal
workflow — assess → (clinician gap-fill) → draft → human approval → submit →
track → (approved | denied → appeal → resubmit) — but in-process, so the API,
the UI, and the offline test suite all run with no Temporal server.

Design points:
- All model/payer work is injected as async callables (``Deps``) so tests swap
  in fakes and production wires the real LangGraph sub-graphs + payer tool.
- Human input (coordinator decision, clinician answers, payer webhooks) arrives
  through methods that set per-case :class:`asyncio.Event` gates the driver
  awaits — the in-process analogue of Temporal signals.
- Every transition publishes a timeline event (SSE) and updates the record.
- HITL routing (coordinator vs. manager) comes from :mod:`clearance.hitl`.
- Terminal outcomes are written to episodic memory (T7.4).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from clearance.api.store import CaseRecord, CaseStore, EventBus
from clearance.hitl.policies import Override, record_override, route_for_review
from clearance.memory.episodic import Episode, EpisodicMemory

AssessFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
DraftFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
AppealFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
SubmitFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

MAX_APPEALS = 2
# Rough projected spend per case stage; real cost accounting lands in Phase 10.
COST_PER_AGENT_DECISION = 0.012


@dataclass
class Deps:
    assess: AssessFn
    draft: DraftFn
    submit: SubmitFn
    appeal: AppealFn
    memory: EpisodicMemory


@dataclass
class _Gates:
    clinician: asyncio.Event
    coordinator: asyncio.Event
    payer: asyncio.Event
    clinician_answers: dict[str, Any]
    coordinator_decision: str | None
    coordinator_actor: str
    payer_update: dict[str, Any] | None
    seen_webhook_ids: set[str]


class CaseService:
    def __init__(self, deps: Deps, store: CaseStore, bus: EventBus) -> None:
        self._deps = deps
        self._store = store
        self._bus = bus
        self._gates: dict[str, _Gates] = {}
        self._tasks: dict[str, asyncio.Task[None]] = {}

    @property
    def store(self) -> CaseStore:
        return self._store

    @property
    def bus(self) -> EventBus:
        return self._bus

    @property
    def memory(self) -> EpisodicMemory:
        return self._deps.memory

    # --- lifecycle -------------------------------------------------------- #

    async def create_case(self, payload: dict[str, Any]) -> CaseRecord:
        rec = CaseRecord(
            case_id=payload["case_id"],
            tenant_id=payload["tenant_id"],
            patient_id=payload["patient_id"],
            payer=payload["payer"],
            procedure=payload["procedure"],
            as_of=payload["as_of"],
        )
        await self._store.put(rec)
        self._gates[rec.case_id] = _Gates(
            clinician=asyncio.Event(),
            coordinator=asyncio.Event(),
            payer=asyncio.Event(),
            clinician_answers={},
            coordinator_decision=None,
            coordinator_actor="",
            payer_update=None,
            seen_webhook_ids=set(),
        )
        self._bus.publish(rec.case_id, "created", "stage", "Case created")
        self._tasks[rec.case_id] = asyncio.create_task(self._drive(rec.case_id))
        return rec

    async def wait_until_idle(self, case_id: str) -> None:
        """Test helper: await the driver reaching a human gate or terminating."""
        task = self._tasks.get(case_id)
        if task is None:
            return
        # Let the driver advance to its next await point.
        for _ in range(200):
            await asyncio.sleep(0)
            if task.done():
                exc = task.exception()
                if exc is not None:
                    raise exc  # surface driver crashes in tests
                return
            rec = self._store.get(case_id)
            if rec and rec.stage in _HUMAN_GATES:
                return

    async def aclose(self) -> None:
        for task in self._tasks.values():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    # --- human inputs (signals) ------------------------------------------ #

    def submit_clinician_answers(self, case_id: str, answers: dict[str, Any]) -> None:
        g = self._gates[case_id]
        g.clinician_answers.update(answers)
        g.clinician.set()
        self._bus.publish(case_id, "awaiting_clinician", "human", "Clinician answered gaps")

    def submit_coordinator_decision(
        self, case_id: str, decision: str, actor_role: str = "coordinator", note: str = ""
    ) -> None:
        g = self._gates[case_id]
        g.coordinator_decision = decision
        g.coordinator_actor = actor_role
        rec = self._store.get(case_id)
        if rec is not None and decision in ("approve", "reject"):
            agent_said = "approve" if all(
                d.get("status") == "met" for d in rec.decisions
            ) else "reject"
            if agent_said != decision or note:
                record_override(
                    Override(
                        case_id=case_id,
                        tenant_id=rec.tenant_id,
                        payer=rec.payer,
                        procedure=rec.procedure,
                        actor_role=actor_role,
                        action=decision,
                        agent_verdict=rec.verdict,
                        agent_decisions=rec.decisions,
                        note=note,
                    )
                )
        g.coordinator.set()
        self._bus.publish(case_id, "awaiting_approval", "human", f"{actor_role} {decision}")

    def payer_webhook(self, case_id: str, event_id: str, update: dict[str, Any]) -> bool:
        """Deliver a payer status update. Returns False if the event is a dup."""
        g = self._gates.get(case_id)
        if g is None:
            return False
        if event_id in g.seen_webhook_ids:
            return False  # idempotent: ignore replayed/duplicate webhooks
        g.seen_webhook_ids.add(event_id)
        g.payer_update = update
        g.payer.set()
        self._bus.publish(
            case_id, "tracking", "payer", f"Payer update: {update.get('status')}", **update
        )
        return True

    # --- driver ----------------------------------------------------------- #

    def _set_stage(self, rec: CaseRecord, stage: str, message: str, **data: Any) -> None:
        rec.stage = stage
        self._store.touch(rec.case_id)
        self._bus.publish(rec.case_id, stage, "stage", message, **data)

    async def _drive(self, case_id: str) -> None:
        rec = self._store.get(case_id)
        assert rec is not None
        g = self._gates[case_id]
        try:
            await self._assess(rec, g)
            while True:  # appeal loop with resubmit
                await self._draft(rec)
                if not await self._approval_gate(rec, g):
                    return  # rejected by a human
                status = await self._submit(rec, g)
                status = await self._track(rec, g, status)
                if status == "approved":
                    self._finish(rec, "approved")
                    return
                if rec.appeal_cycles >= MAX_APPEALS:
                    self._finish(rec, "denied")
                    return
                await self._appeal(rec)
                rec.appeal_cycles += 1
                g.coordinator.clear()
                g.coordinator_decision = None
        except Exception as exc:  # pragma: no cover - defensive
            rec.errors.append(str(exc))
            self._set_stage(rec, "error", f"Case failed: {exc}", error=str(exc))

    async def _assess(self, rec: CaseRecord, g: _Gates) -> None:
        self._set_stage(rec, "assessing", "Assessing chart against policy criteria")
        result = await self._deps.assess(_assess_input(rec))
        rec.policy_version = result.get("policy_version")
        rec.checklist = result.get("checklist", [])
        rec.decisions = result.get("decisions", [])
        rec.evidence_cards = result.get("evidence_cards", [])
        rec.errors += result.get("errors", [])
        agent_decisions = sum(1 for d in rec.decisions if d.get("method") == "agent")
        rec.est_cost_usd = round(agent_decisions * COST_PER_AGENT_DECISION, 4)
        self._bus.publish(
            rec.case_id, "assessing", "decision", "Criteria evaluated",
            met=sum(1 for d in rec.decisions if d.get("status") == "met"),
            total=len(rec.decisions),
        )
        unknown = [d for d in rec.decisions if d.get("status") == "unknown"]
        if unknown:
            rec.clinician_questions = [
                _question_for(rec, d) for d in unknown
            ]
            self._set_stage(
                rec, "awaiting_clinician", "Gaps need a clinician's input",
                questions=rec.clinician_questions,
            )
            await g.clinician.wait()
            # Apply answers: a provided answer marks that criterion met.
            for d in rec.decisions:
                if d.get("status") == "unknown" and d["criterion_id"] in g.clinician_answers:
                    d["status"] = "met"
                    d["method"] = "agent"
                    d["rationale"] = "Provided by clinician"

    async def _draft(self, rec: CaseRecord) -> None:
        self._set_stage(rec, "drafting", "Drafting cited medical-necessity letter")
        state = _draft_input(rec)
        # T7.4: retrieve the per-payer playbook learned from past outcomes and
        # pass its guidance to the drafter so it can pre-empt common denials.
        note = self._deps.memory.get_note(rec.payer, rec.procedure, rec.policy_version)
        if note is not None:
            state["playbook_hint"] = note.guidance
            self._bus.publish(
                rec.case_id, "drafting", "decision", "Applied payer playbook",
                guidance=note.guidance,
            )
        result = await self._deps.draft(state)
        rec.verdict = result.get("verdict")
        rec.letter = result.get("letter")
        rec.packet = result.get("packet")
        self._bus.publish(
            rec.case_id, "drafting", "decision", f"Verifier verdict: {rec.verdict}",
            verdict=rec.verdict,
        )

    async def _approval_gate(self, rec: CaseRecord, g: _Gates) -> bool:
        route = route_for_review(
            decisions=rec.decisions,
            est_cost_usd=rec.est_cost_usd,
            appeal_cycles=rec.appeal_cycles,
        )
        rec.needs_manager = route.needs_manager
        rec.manager_reasons = list(route.reasons)
        rec.assigned_role = route.assigned_role
        self._set_stage(
            rec, "awaiting_approval",
            f"Awaiting {route.assigned_role} approval",
            assigned_role=route.assigned_role,
            reasons=rec.manager_reasons,
        )
        await g.coordinator.wait()
        if g.coordinator_decision == "reject":
            self._finish(rec, "rejected")
            return False
        return True

    async def _submit(self, rec: CaseRecord, g: _Gates) -> str:
        rec.attempt += 1
        self._set_stage(rec, "submitting", f"Submitting to payer (attempt {rec.attempt})")
        resp = await self._deps.submit(
            {
                "case_id": rec.case_id,
                "tenant_id": rec.tenant_id,
                "procedure": rec.procedure,
                "packet": rec.packet or {},
                "approval_token": "coordinator-approved",
                "attempt": rec.attempt,
            }
        )
        rec.claim_id = resp.get("claim_id")
        rec.denial_reason = resp.get("denial_reason")
        return str(resp.get("status", "pended"))

    async def _track(self, rec: CaseRecord, g: _Gates, status: str) -> str:
        self._set_stage(rec, "tracking", "Tracking payer decision", status=status)
        while status in ("pended", "more_info"):
            g.payer.clear()
            g.payer_update = None
            await g.payer.wait()
            upd: dict[str, Any] = g.payer_update or {}
            status = str(upd.get("status", status))
            rec.denial_reason = upd.get("denial_reason", rec.denial_reason)
        return status

    async def _appeal(self, rec: CaseRecord) -> None:
        self._set_stage(
            rec, "appealing", f"Denied ({rec.denial_reason}); drafting appeal",
            denial_reason=rec.denial_reason,
        )
        state = _draft_input(rec)
        state["denial_reason"] = rec.denial_reason
        result = await self._deps.appeal(state)
        rec.packet = {**(rec.packet or {}), "appeal": result.get("appeal")}

    def _finish(self, rec: CaseRecord, outcome: str) -> None:
        rec.outcome = outcome
        self._set_stage(rec, "done", f"Case {outcome}", outcome=outcome)
        if outcome in ("approved", "denied"):
            self._deps.memory.record(
                Episode(
                    payer=rec.payer,
                    procedure=rec.procedure,
                    outcome=outcome,
                    denial_reason=rec.denial_reason if outcome == "denied" else None,
                    policy_version=rec.policy_version,
                    case_id=rec.case_id,
                )
            )


_HUMAN_GATES = {"awaiting_clinician", "awaiting_approval", "tracking", "done", "error"}


def _assess_input(rec: CaseRecord) -> dict[str, Any]:
    return {
        "case_id": rec.case_id,
        "tenant_id": rec.tenant_id,
        "patient_id": rec.patient_id,
        "payer": rec.payer,
        "procedure": rec.procedure,
        "as_of": rec.as_of,
    }


def _draft_input(rec: CaseRecord) -> dict[str, Any]:
    return {
        "case_id": rec.case_id,
        "tenant_id": rec.tenant_id,
        "patient_id": rec.patient_id,
        "payer": rec.payer,
        "procedure": rec.procedure,
        "as_of": rec.as_of,
        "policy_version": rec.policy_version,
        "checklist": rec.checklist,
        "decisions": rec.decisions,
        "evidence_cards": rec.evidence_cards,
    }


def _question_for(rec: CaseRecord, decision: dict[str, Any]) -> str:
    cid = decision.get("criterion_id", "")
    text = next(
        (c.get("text", cid) for c in rec.checklist if c.get("id") == cid), cid
    )
    return f"Unable to confirm from the chart: {text}. Can you confirm or provide documentation?"
