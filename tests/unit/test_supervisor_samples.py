"""T5.8 done-when: offline run of each sub-graph on 3 sample cases, using the
real ground-truth checklists in data/policies/parsed/."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentcore.audit import AuditLog
from agentcore.llm import _set_complete_fn
from clearance.agents.criteria import _JudgeResult
from clearance.agents.state import new_case_state
from clearance.agents.supervisor import (
    build_appeal,
    build_assess,
    build_draft,
    make_checklist_loader,
)
from clearance.db import make_engine, make_session_factory
from clearance.fhir.loader import load_bundle
from clearance.models import Base

AS_OF = "2020-12-01"


def _patient(pid: str, *resources: dict[str, Any]) -> dict[str, Any]:
    entries = [{"resource": {"resourceType": "Patient", "id": pid, "birthDate": "1960-01-01"}}]
    entries += [{"resource": r} for r in resources]
    return {"resourceType": "Bundle", "entry": entries}


def _procedure(rid: str, pid: str, code: str, when: str) -> dict[str, Any]:
    return {
        "resourceType": "Procedure",
        "id": rid,
        "subject": {"reference": f"Patient/{pid}"},
        "performedDateTime": when,
        "code": {"coding": [{"code": code}]},
    }


def _condition(rid: str, pid: str, code: str, when: str) -> dict[str, Any]:
    return {
        "resourceType": "Condition",
        "id": rid,
        "subject": {"reference": f"Patient/{pid}"},
        "onsetDateTime": when,
        "code": {"coding": [{"code": code}]},
    }


# 3 sample cases, one per M1 procedure, seeded to satisfy their rule criteria.
CASES = [
    (
        "lumbar_spine_mri",
        "pat-lumbar",
        [_procedure("p-lx", "pat-lumbar", "97110", "2020-09-01T00:00:00Z")],
    ),
    ("knee_mri", "pat-knee", []),  # no pregnancy condition -> contraindication rule met
    ("ct_abdomen", "pat-ct", [_condition("c-ct", "pat-ct", "R10.0", "2020-06-01T00:00:00Z")]),
]


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = make_session_factory(engine)
    async with f() as s:
        for _, pid, resources in CASES:
            await load_bundle(s, _patient(pid, *resources), clinic_id="clinic-a")
        await s.commit()
    yield f
    await engine.dispose()


async def _version(payer: str, procedure: str, as_of: str) -> str | None:
    return "test-version"


async def test_subgraphs_run_on_three_cases(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async def fake_complete(messages: Any, *, schema: Any, **kwargs: Any) -> Any:
        return _JudgeResult(status="met", confidence=0.8, rationale="meets criterion")

    _set_complete_fn(fake_complete)
    try:
        load_checklist = make_checklist_loader()
        assess = build_assess(factory, AuditLog(), _version, load_checklist)
        draft = build_draft()
        appeal = build_appeal()

        for procedure, pid, _resources in CASES:
            state = new_case_state(
                case_id=f"case-{procedure}",
                tenant_id="clinic-a",
                patient_id=pid,
                payer="medicare",
                procedure=procedure,
                as_of=AS_OF,
            )
            assessed = await assess.ainvoke(state)
            # Every criterion in the real checklist got a decision.
            assert assessed["checklist"], f"{procedure}: no checklist loaded"
            assert len(assessed["decisions"]) == len(assessed["checklist"])

            drafted = await draft.ainvoke(assessed)
            assert drafted["verdict"] in {"pass", "revise", "escalate"}
            assert "letter" in drafted

            appealed = await appeal.ainvoke({**assessed, "denial_reason": "criteria_not_met"})
            assert appealed["appeal"]["kind"] == "appeal"
    finally:
        _set_complete_fn(None)
