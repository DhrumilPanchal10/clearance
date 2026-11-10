"""PriorAuthCase workflow tests via Temporal's time-skipping env (T6.2/T6.3).

Activities are mocked (registered under the same names), so no DB/payer/LLM is
touched; this verifies the orchestration state machine, signals, query,
approval gate, and the denial -> appeal -> Continue-As-New loop. The test skips
if the Temporal test server cannot be started (e.g. offline CI with no binary).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest
from temporalio import activity
from temporalio.client import WorkflowFailureError
from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker

from clearance.workflows._names import APPEAL, ASSESS, DRAFT, SUBMIT
from clearance.workflows.prior_auth import PriorAuthCase

# Mutable submit behavior per test.
_SUBMIT: dict[str, Any] = {"status": "approved", "denial_reason": None}

TASK_QUEUE = "test-pa"
CASE_INPUT = {
    "case_id": "case-1",
    "tenant_id": "clinic-a",
    "patient_id": "pat-1",
    "payer": "medicare",
    "procedure": "lumbar_spine_mri",
    "as_of": "2020-12-01",
}


@activity.defn(name=ASSESS)
async def mock_assess(inp: dict[str, Any]) -> dict[str, Any]:
    return {
        **inp,
        "policy_version": "L34220",
        "checklist": [{"id": "c1", "text": "x", "kind": "rule", "rule_spec": {}}],
        "decisions": [
            {"criterion_id": "c1", "status": "met", "evidence_refs": ["r1"], "method": "rule"}
        ],
        "errors": [],
    }


@activity.defn(name=DRAFT)
async def mock_draft(state: dict[str, Any]) -> dict[str, Any]:
    return {
        "verdict": "pass",
        "letter": {"title": "LMN"},
        "packet": {"case_id": state.get("case_id")},
        "revision_count": 0,
    }


@activity.defn(name=SUBMIT)
async def mock_submit(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "claim_id": "PA-1",
        "status": _SUBMIT["status"],
        "denial_reason": _SUBMIT["denial_reason"],
    }


@activity.defn(name=APPEAL)
async def mock_appeal(state: dict[str, Any]) -> dict[str, Any]:
    return {"appeal": {"kind": "appeal"}}


MOCKS = [mock_assess, mock_draft, mock_submit, mock_appeal]


async def _env() -> WorkflowEnvironment:
    try:
        return await WorkflowEnvironment.start_time_skipping()
    except Exception as exc:  # pragma: no cover - environment dependent
        pytest.skip(f"Temporal test server unavailable: {exc}")


async def test_happy_path_approved() -> None:
    _SUBMIT.update(status="approved", denial_reason=None)
    env = await _env()
    async with (
        env,
        Worker(env.client, task_queue=TASK_QUEUE, workflows=[PriorAuthCase], activities=MOCKS),
    ):
        handle = await env.client.start_workflow(
            PriorAuthCase.run, CASE_INPUT, id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE
        )
        await handle.signal(PriorAuthCase.coordinator_decision, "approve")
        result = await handle.result()
    assert result["outcome"] == "approved"


async def test_reject_path() -> None:
    _SUBMIT.update(status="approved", denial_reason=None)
    env = await _env()
    async with (
        env,
        Worker(env.client, task_queue=TASK_QUEUE, workflows=[PriorAuthCase], activities=MOCKS),
    ):
        handle = await env.client.start_workflow(
            PriorAuthCase.run, CASE_INPUT, id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE
        )
        await handle.signal(PriorAuthCase.coordinator_decision, "reject")
        result = await handle.result()
    assert result["outcome"] == "rejected"


async def test_query_reports_stage() -> None:
    _SUBMIT.update(status="approved", denial_reason=None)
    env = await _env()
    async with (
        env,
        Worker(env.client, task_queue=TASK_QUEUE, workflows=[PriorAuthCase], activities=MOCKS),
    ):
        handle = await env.client.start_workflow(
            PriorAuthCase.run, CASE_INPUT, id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE
        )
        state = await handle.query(PriorAuthCase.current_state)
        assert "stage" in state and "outcome" in state
        await handle.signal(PriorAuthCase.coordinator_decision, "approve")
        await handle.result()


async def test_denial_appeal_continue_as_new() -> None:
    # Payer always denies -> appeal loop -> Continue-As-New until the appeal budget.
    _SUBMIT.update(status="denied", denial_reason="criteria_not_met")
    env = await _env()
    async with (
        env,
        Worker(env.client, task_queue=TASK_QUEUE, workflows=[PriorAuthCase], activities=MOCKS),
    ):
        handle = await env.client.start_workflow(
            PriorAuthCase.run, CASE_INPUT, id=f"wf-{uuid.uuid4()}", task_queue=TASK_QUEUE
        )

        async def drive() -> None:
            for _ in range(30):
                try:
                    st = await handle.query(PriorAuthCase.current_state)
                except (WorkflowFailureError, RuntimeError):
                    return
                if st.get("outcome"):
                    return
                if st.get("stage") == "awaiting_approval":
                    await handle.signal(PriorAuthCase.coordinator_decision, "approve")
                await asyncio.sleep(0.2)

        driver = asyncio.ensure_future(drive())
        result = await handle.result()
        await driver
    assert result["outcome"] == "denied"
    assert result["appeal_cycles"] == 2  # MAX_APPEALS
    _SUBMIT.update(status="approved", denial_reason=None)
