"""Temporal activities (plan T6.1).

All I/O lives here (never in workflow code): running the LangGraph sub-graphs,
and the payer write. Dependencies are injected once at worker startup via
``set_activity_deps`` so activities stay importable in the workflow sandbox-free
process. Payloads crossing the activity boundary are plain JSON-able dicts.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from temporalio import activity
from temporalio.exceptions import ApplicationError

from agentcore.audit import AuditLog
from clearance.agents.state import CriterionDecision, new_case_state
from clearance.agents.supervisor import (
    ChecklistLoader,
    PolicyVersionLookup,
    build_appeal,
    build_assess,
    build_draft,
)
from clearance.mcp_servers.payer import build_payer_tools
from clearance.workflows._names import APPEAL, ASSESS, DRAFT, SUBMIT


@dataclass
class ActivityDeps:
    session_factory: Any
    audit_log: AuditLog
    payer_client: httpx.AsyncClient
    get_version: PolicyVersionLookup
    load_checklist: ChecklistLoader


_deps: ActivityDeps | None = None


def set_activity_deps(deps: ActivityDeps) -> None:
    global _deps
    _deps = deps


def _require() -> ActivityDeps:
    if _deps is None:
        raise RuntimeError("activity deps not configured; call set_activity_deps()")
    return _deps


def _rehydrate_decisions(items: list[dict[str, Any]]) -> list[CriterionDecision]:
    return [CriterionDecision.model_validate(d) for d in items]


@activity.defn(name=ASSESS)
async def assess_case(inp: dict[str, Any]) -> dict[str, Any]:
    deps = _require()
    graph = build_assess(
        deps.session_factory, deps.audit_log, deps.get_version, deps.load_checklist
    )
    state = new_case_state(
        case_id=inp["case_id"],
        tenant_id=inp["tenant_id"],
        patient_id=inp["patient_id"],
        payer=inp["payer"],
        procedure=inp["procedure"],
        as_of=inp["as_of"],
    )
    result = await graph.ainvoke(dict(state))
    return {
        "case_id": inp["case_id"],
        "tenant_id": inp["tenant_id"],
        "patient_id": inp["patient_id"],
        "payer": result.get("payer", inp["payer"]),
        "procedure": result.get("procedure", inp["procedure"]),
        "as_of": inp["as_of"],
        "policy_version": result.get("policy_version"),
        "checklist": result.get("checklist", []),
        "decisions": [d.model_dump() for d in result.get("decisions", [])],
        "errors": result.get("errors", []),
    }


@activity.defn(name=DRAFT)
async def draft_case(state: dict[str, Any]) -> dict[str, Any]:
    graph = build_draft()
    work = dict(state)
    work["decisions"] = _rehydrate_decisions(state.get("decisions", []))
    result = await graph.ainvoke(work)
    return {
        "verdict": result.get("verdict"),
        "letter": result.get("letter"),
        "packet": result.get("packet"),
        "revision_count": result.get("revision_count", 0),
    }


@activity.defn(name=SUBMIT)
async def submit_case(args: dict[str, Any]) -> dict[str, Any]:
    deps = _require()
    tools = build_payer_tools(deps.payer_client, deps.audit_log)
    from agentcore.auth import UserClaims
    from clearance.mcp_servers.base import ToolContext

    clinic = args["tenant_id"]
    ctx = ToolContext(
        claims=UserClaims(user_id="agent", tenant_id=clinic, role="coordinator", raw={}),
        clinic_id=clinic,
    )
    try:
        result: dict[str, Any] = await tools.submit_prior_auth(
            ctx,
            case_id=args["case_id"],
            procedure=args["procedure"],
            packet=args.get("packet", {}),
            approval_token=args["approval_token"],
            attempt=args.get("attempt", 1),
            callback_url=args.get("callback_url"),
        )
        return result
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # 4xx = our bad request: do not retry. 5xx/429 stay retryable.
        if 400 <= status < 500 and status != 429:
            raise ApplicationError(f"payer rejected ({status})", non_retryable=True) from exc
        raise


@activity.defn(name=APPEAL)
async def appeal_case(state: dict[str, Any]) -> dict[str, Any]:
    graph = build_appeal()
    work = dict(state)
    work["decisions"] = _rehydrate_decisions(state.get("decisions", []))
    result = await graph.ainvoke(work)
    return {"appeal": result.get("appeal")}


ALL_ACTIVITIES = [assess_case, draft_case, submit_case, appeal_case]
