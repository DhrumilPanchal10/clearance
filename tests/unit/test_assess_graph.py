"""End-to-end offline test of the assess sub-graph (T5.2-T5.4, T5.8)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentcore.audit import AuditLog
from agentcore.llm import _set_complete_fn
from clearance.agents.criteria import _JudgeResult, make_criteria_node
from clearance.agents.evidence import make_evidence_node
from clearance.agents.graphs import build_assess_graph
from clearance.agents.intake import make_intake_node
from clearance.agents.policy import make_policy_node
from clearance.agents.state import new_case_state
from clearance.db import make_engine, make_session_factory
from clearance.fhir.loader import load_bundle
from clearance.mcp_servers.fhir_read import build_fhir_read_tools
from clearance.models import Base

PATIENT = "pat-1"

# A lumbar-like checklist: one rule (conservative therapy) + one judgment (red flag).
CHECKLIST = [
    {
        "id": "medicare:lumbar_spine_mri:L34220:c1",
        "text": "A red-flag condition is present.",
        "kind": "judgment",
        "rule_spec": None,
    },
    {
        "id": "medicare:lumbar_spine_mri:L34220:c2",
        "text": "At least 4 weeks of conservative therapy completed.",
        "kind": "rule",
        "rule_spec": {"kind": "conservative_therapy", "codes": ["97110"], "min_duration_days": 28},
    },
]


def _bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": PATIENT, "birthDate": "1960-01-01"}},
            {
                "resource": {
                    "resourceType": "Procedure",
                    "id": "pt-1",
                    "subject": {"reference": f"Patient/{PATIENT}"},
                    "performedDateTime": "2020-09-01T00:00:00Z",  # > 28 days before as_of
                    "code": {"coding": [{"code": "97110"}]},
                }
            },
        ],
    }


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = make_session_factory(engine)
    async with f() as s:
        await load_bundle(s, _bundle(), clinic_id="clinic-a")
        await s.commit()
    yield f
    await engine.dispose()


async def _get_version(payer: str, procedure: str, as_of: str) -> str | None:
    return "L34220"


async def _load_checklist(payer: str, procedure: str, version: str) -> list[dict[str, Any]]:
    return CHECKLIST


async def test_assess_graph_decides_rule_and_judgment(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    # Stub the judgment LLM: the red-flag criterion is judged not_met.
    async def fake_complete(messages: Any, *, schema: Any, **kwargs: Any) -> Any:
        return _JudgeResult(status="not_met", confidence=0.7, rationale="no red flags")

    _set_complete_fn(fake_complete)
    try:
        tools = build_fhir_read_tools(factory, AuditLog())
        graph = build_assess_graph(
            make_intake_node(_get_version),
            make_policy_node(_load_checklist),
            make_evidence_node(tools, _load_checklist),
            make_criteria_node(tools),
        )
        state = new_case_state(
            case_id="case-1",
            tenant_id="clinic-a",
            patient_id=PATIENT,
            payer="Medicare",
            procedure="Lumbar_Spine_MRI",
            as_of="2020-12-01",
        )
        result = await graph.ainvoke(state)
    finally:
        _set_complete_fn(None)

    assert result["policy_version"] == "L34220"
    assert result["payer"] == "medicare"  # normalized by intake
    decisions = {d.criterion_id: d for d in result["decisions"]}
    # Rule criterion decided in Python: ~3 months of therapy >= 28 days -> met.
    rule = decisions["medicare:lumbar_spine_mri:L34220:c2"]
    assert rule.method == "rule" and rule.status == "met"
    assert rule.evidence_refs == ["pt-1"]
    # Judgment criterion decided by the (stubbed) agent.
    judg = decisions["medicare:lumbar_spine_mri:L34220:c1"]
    assert judg.method == "agent" and judg.status == "not_met"
    # Evidence cards were built for every criterion.
    assert len(result["evidence_cards"]) == 2
