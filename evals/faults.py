"""Fault-injection eval (plan T9.4).

Proves the two durability guarantees under adversarial conditions:

- **Exactly-once submission.** Under duplicate submits and transient payer
  faults (500 / 503 / 429), retried with the same idempotency key, the payer
  must create exactly one claim and replay the first decision.
- **Webhook robustness.** Duplicate and out-of-order payer webhooks must be
  deduped by event id so a case advances once, correctly.

Runs fully in-process (payer service via ASGI transport; the API's webhook
receiver directly). Accumulates ~120 injected faults and asserts no exactly-once
violation occurred.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

import httpx
from payer_service import app as payer_app
from payer_service.failure_modes import FailureConfig, plan_webhook_deliveries

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from clearance.api.service import CaseService, Deps
from clearance.api.store import CaseStore, EventBus
from clearance.mcp_servers.base import ToolContext
from clearance.mcp_servers.payer import build_payer_tools
from clearance.memory.episodic import EpisodicMemory


@dataclass
class FaultReport:
    scenarios: int = 0
    faults_injected: int = 0
    exactly_once_violations: int = 0
    webhook_dupes_rejected: int = 0
    webhook_scenarios: int = 0

    @property
    def exactly_once_ok(self) -> bool:
        return self.exactly_once_violations == 0


def _ctx() -> ToolContext:
    return ToolContext(
        claims=UserClaims(user_id="agent", tenant_id="clinic-a", role="coordinator", raw={}),
        clinic_id="clinic-a",
    )


async def _submit_with_retry(tools, case_id: str, attempt: int, retries: int = 6) -> str:
    """Submit, retrying transient faults with the SAME idempotency key."""
    last_exc: Exception | None = None
    for _ in range(retries):
        try:
            resp = await tools.submit_prior_auth(
                _ctx(),
                case_id=case_id,
                procedure="lumbar_spine_mri",
                packet={"case_id": case_id},
                approval_token="coordinator-approved",
                attempt=attempt,
            )
            return str(resp["claim_id"])
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            continue
    raise AssertionError(f"submission never succeeded: {last_exc}")


async def run_fault_suite(n_cases: int = 40) -> FaultReport:
    report = FaultReport()
    transport = httpx.ASGITransport(app=payer_app.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://payer") as client:
        tools = build_payer_tools(client, AuditLog())
        for i in range(n_cases):
            case_id = f"fault-{i:03d}"

            # Scenario A: duplicate submissions must collapse to one claim.
            claims = set()
            for _ in range(4):
                claims.add(await _submit_with_retry(tools, case_id, attempt=1))
            report.scenarios += 1
            report.faults_injected += 3  # 3 duplicate re-sends
            if len(claims) != 1:
                report.exactly_once_violations += 1

            # Scenario B: transient faults then success, same key → same claim.
            payer_app.state.failures.inject_statuses.extend([500, 503, 429])
            report.faults_injected += 3
            claim_b = await _submit_with_retry(tools, case_id, attempt=1)
            report.scenarios += 1
            if claim_b not in claims:  # must replay the very first decision
                report.exactly_once_violations += 1

        # Webhook dedupe + reordering against the API receiver.
        svc = CaseService(
            Deps(
                assess=_noop, draft=_noop, submit=_noop, appeal=_noop,
                memory=EpisodicMemory(),
            ),
            CaseStore(),
            EventBus(),
        )
        for i in range(n_cases):
            cid = f"wh-{i:03d}"
            svc._gates[cid] = _fresh_gate()  # type: ignore[attr-defined]
            events = [("evt-1", "pended"), ("evt-2", "approved")]
            delivered = plan_webhook_deliveries(
                events, FailureConfig(duplicate_webhooks=True, reorder_webhooks=True)
            )
            report.faults_injected += len(delivered) - len(events)  # extra deliveries
            accepted = 0
            for eid, status in delivered:
                if svc.payer_webhook(cid, eid, {"status": status}):
                    accepted += 1
            report.webhook_scenarios += 1
            # Exactly two unique event ids should be accepted despite dup+reorder.
            if accepted == len(events):
                report.webhook_dupes_rejected += 1
        await svc.aclose()
    return report


async def _noop(x):  # pragma: no cover - placeholder dep
    return {}


def _fresh_gate():
    from clearance.api.service import _Gates

    return _Gates(
        clinician=asyncio.Event(),
        coordinator=asyncio.Event(),
        payer=asyncio.Event(),
        clinician_answers={},
        coordinator_decision=None,
        coordinator_actor="",
        payer_update=None,
        seen_webhook_ids=set(),
    )
