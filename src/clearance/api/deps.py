"""Dependency wiring for the API (plan T7.1).

Builds a :class:`CaseService` backed by the real LangGraph sub-graphs, the FHIR
database, the payer write tool, and episodic memory. The sub-graphs are invoked
through thin async adapters that serialise their Pydantic outputs to the plain
dicts the orchestrator and the wire protocol use (the same boundary the Temporal
activities enforce).

Tests build a service with fake adapters instead (see ``tests/unit/test_api``),
so nothing here needs a database, payer, or LLM to exercise the API.
"""

from __future__ import annotations

from typing import Any

import httpx

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from clearance.agents.state import new_case_state
from clearance.agents.supervisor import (
    build_appeal,
    build_assess,
    build_draft,
    make_checklist_loader,
    make_policy_version_lookup,
)
from clearance.api.service import CaseService, Deps
from clearance.api.store import CaseStore, EventBus
from clearance.config import settings
from clearance.db import make_engine, make_session_factory
from clearance.mcp_servers.base import ToolContext
from clearance.mcp_servers.payer import build_payer_tools
from clearance.memory.episodic import EpisodicMemory


def build_production_deps() -> Deps:
    session_factory = make_session_factory(make_engine())
    audit = AuditLog()
    get_version = make_policy_version_lookup(session_factory)
    load_checklist = make_checklist_loader()
    payer_client = httpx.AsyncClient(base_url=settings.payer_base_url, timeout=30)
    payer_tools = build_payer_tools(payer_client, audit)

    assess_graph = build_assess(session_factory, audit, get_version, load_checklist)
    draft_graph = build_draft()
    appeal_graph = build_appeal()

    async def assess(inp: dict[str, Any]) -> dict[str, Any]:
        state = new_case_state(
            case_id=inp["case_id"],
            tenant_id=inp["tenant_id"],
            patient_id=inp["patient_id"],
            payer=inp["payer"],
            procedure=inp["procedure"],
            as_of=inp["as_of"],
        )
        result = await assess_graph.ainvoke(dict(state))
        return {
            "policy_version": result.get("policy_version"),
            "checklist": result.get("checklist", []),
            "decisions": [d.model_dump() for d in result.get("decisions", [])],
            "evidence_cards": [c.model_dump() for c in result.get("evidence_cards", [])],
            "errors": result.get("errors", []),
        }

    async def draft(state: dict[str, Any]) -> dict[str, Any]:
        from clearance.agents.state import CriterionDecision

        work = dict(state)
        work["decisions"] = [CriterionDecision.model_validate(d) for d in state.get("decisions", [])]
        result = await draft_graph.ainvoke(work)
        return {
            "verdict": result.get("verdict"),
            "letter": result.get("letter"),
            "packet": result.get("packet"),
        }

    async def appeal(state: dict[str, Any]) -> dict[str, Any]:
        from clearance.agents.state import CriterionDecision

        work = dict(state)
        work["decisions"] = [CriterionDecision.model_validate(d) for d in state.get("decisions", [])]
        result = await appeal_graph.ainvoke(work)
        return {"appeal": result.get("appeal")}

    async def submit(args: dict[str, Any]) -> dict[str, Any]:
        clinic = args["tenant_id"]
        ctx = ToolContext(
            claims=UserClaims(user_id="agent", tenant_id=clinic, role="coordinator", raw={}),
            clinic_id=clinic,
        )
        resp: dict[str, Any] = await payer_tools.submit_prior_auth(
            ctx,
            case_id=args["case_id"],
            procedure=args["procedure"],
            packet=args.get("packet", {}),
            approval_token=args["approval_token"],
            attempt=args.get("attempt", 1),
        )
        return resp

    return Deps(
        assess=assess,
        draft=draft,
        submit=submit,
        appeal=appeal,
        memory=EpisodicMemory(),
    )


def build_service(deps: Deps | None = None) -> CaseService:
    return CaseService(deps or build_production_deps(), CaseStore(), EventBus())
