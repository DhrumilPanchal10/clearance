"""PriorAuthCase workflow (plan T6.2).

Durable orchestration for one case: assess → draft → coordinator approval →
submit → track → (approved | denied → appeal → resubmit). Deterministic: all
I/O is in activities, waits use timers, no wall-clock/random. Human input
arrives as signals; progress is observable via the current_state query;
Continue-As-New keeps history bounded across appeal cycles.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy

from clearance.workflows._names import (
    APPEAL,
    ASSESS,
    DRAFT,
    QRY_CURRENT_STATE,
    SIG_CLINICIAN_ANSWER,
    SIG_COORDINATOR_DECISION,
    SIG_PAYER_UPDATE,
    SUBMIT,
)

MAX_APPEALS = 2

_LLM_RETRY = RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=1))
_SUBMIT_RETRY = RetryPolicy(maximum_attempts=5, initial_interval=timedelta(seconds=1))


@workflow.defn(name="PriorAuthCase")
class PriorAuthCase:
    def __init__(self) -> None:
        self._stage: str = "created"
        self._outcome: str | None = None
        self._verdict: str | None = None
        self._attempt: int = 0
        self._appeal_cycles: int = 0
        self._reminders: int = 0
        self._denial_reason: str | None = None
        self._coordinator_decision: str | None = None
        self._approval_token: str = ""
        self._clinician_answer: dict[str, Any] | None = None
        self._payer_update: dict[str, Any] | None = None
        self._state: dict[str, Any] = {}

    # --- signals ---------------------------------------------------------- #

    @workflow.signal(name=SIG_COORDINATOR_DECISION)
    def coordinator_decision(self, decision: str) -> None:
        self._coordinator_decision = decision
        if decision == "approve":
            self._approval_token = "coordinator-approved"

    @workflow.signal(name=SIG_CLINICIAN_ANSWER)
    def clinician_answer(self, answer: dict[str, Any]) -> None:
        self._clinician_answer = answer

    @workflow.signal(name=SIG_PAYER_UPDATE)
    def payer_update(self, update: dict[str, Any]) -> None:
        self._payer_update = update

    # --- query ------------------------------------------------------------ #

    @workflow.query(name=QRY_CURRENT_STATE)
    def current_state(self) -> dict[str, Any]:
        return {
            "stage": self._stage,
            "outcome": self._outcome,
            "verdict": self._verdict,
            "attempt": self._attempt,
            "appeal_cycles": self._appeal_cycles,
            "reminders": self._reminders,
            "denial_reason": self._denial_reason,
        }

    # --- helpers ---------------------------------------------------------- #

    async def _wait_with_reminders(self, cond: Callable[[], bool], hours: int = 24) -> None:
        """Block until ``cond`` holds, emitting a reminder nudge on each timeout."""
        use_reminders = workflow.patched("coordinator-and-clinician-reminders")
        while not cond():
            if use_reminders:
                try:
                    await workflow.wait_condition(cond, timeout=timedelta(hours=hours))
                except TimeoutError:
                    self._reminders += 1  # nudge the human; keep waiting
            else:
                await workflow.wait_condition(cond)

    def _result(self) -> dict[str, Any]:
        self._stage = "done"
        return {
            "case_id": self._state.get("case_id"),
            "outcome": self._outcome,
            "attempt": self._attempt,
            "appeal_cycles": self._appeal_cycles,
            "reminders": self._reminders,
        }

    # --- run -------------------------------------------------------------- #

    @workflow.run
    async def run(self, inp: dict[str, Any]) -> dict[str, Any]:
        resume = inp.get("resume")
        if resume:
            self._state = resume["state"]
            self._attempt = resume["attempt"]
            self._appeal_cycles = resume["appeal_cycles"]
        else:
            self._stage = "assessing"
            self._state = await workflow.execute_activity(
                ASSESS, inp, start_to_close_timeout=timedelta(seconds=60), retry_policy=_LLM_RETRY
            )
            # Gap-filling: if any criterion is unknown, ask the clinician.
            if any(d.get("status") == "unknown" for d in self._state.get("decisions", [])):
                self._stage = "awaiting_clinician"
                await self._wait_with_reminders(lambda: self._clinician_answer is not None)

        # Draft the packet + letter.
        self._stage = "drafting"
        drafted = await workflow.execute_activity(
            DRAFT,
            self._state,
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_LLM_RETRY,
        )
        self._verdict = drafted.get("verdict")
        self._state["letter"] = drafted.get("letter")
        self._state["packet"] = drafted.get("packet")

        # HITL: every submission needs coordinator approval. (After Continue-As-New
        # the instance is fresh, so the decision starts cleared without resetting.)
        self._stage = "awaiting_approval"
        await self._wait_with_reminders(lambda: self._coordinator_decision is not None)
        if self._coordinator_decision == "reject":
            self._outcome = "rejected"
            return self._result()

        # Submit (idempotent; retries safe, 4xx non-retryable inside the activity).
        self._attempt += 1
        self._stage = "submitting"
        resp = await workflow.execute_activity(
            SUBMIT,
            {
                "case_id": self._state.get("case_id"),
                "tenant_id": self._state.get("tenant_id"),
                "procedure": self._state.get("procedure"),
                "packet": self._state.get("packet", {}),
                "approval_token": self._approval_token,
                "attempt": self._attempt,
            },
            start_to_close_timeout=timedelta(seconds=30),
            retry_policy=_SUBMIT_RETRY,
        )
        status = resp.get("status")

        # Track: park on a timer until the payer reaches a terminal state.
        self._stage = "tracking"
        while status in ("pended", "more_info"):
            self._payer_update = None
            await self._wait_with_reminders(lambda: self._payer_update is not None)
            upd: dict[str, Any] = self._payer_update or {}
            status = upd.get("status", status)

        if status == "approved":
            self._outcome = "approved"
            return self._result()

        # Denied → appeal, or give up after the appeal budget.
        self._denial_reason = resp.get("denial_reason")
        if self._appeal_cycles >= MAX_APPEALS:
            self._outcome = "denied"
            return self._result()

        self._stage = "appealing"
        appealed = await workflow.execute_activity(
            APPEAL,
            {**self._state, "denial_reason": self._denial_reason},
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=_LLM_RETRY,
        )
        self._state["appeal"] = appealed.get("appeal")

        # Continue-As-New: bound history; the next cycle re-seeks approval + resubmits.
        workflow.continue_as_new(
            {
                "resume": {
                    "state": self._state,
                    "attempt": self._attempt,
                    "appeal_cycles": self._appeal_cycles + 1,
                }
            }
        )
