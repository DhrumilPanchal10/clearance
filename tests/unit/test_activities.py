"""Test the assess activity in-process via ActivityEnvironment (T6.1).

No Temporal server needed — ActivityEnvironment runs the activity function
directly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio.testing import ActivityEnvironment

from agentcore.audit import AuditLog
from agentcore.llm import _set_complete_fn
from clearance.agents.criteria import _JudgeResult
from clearance.db import make_engine, make_session_factory
from clearance.fhir.loader import load_bundle
from clearance.models import Base
from clearance.workflows.activities import ActivityDeps, assess_case, set_activity_deps

CHECKLIST = [
    {"id": "c1", "text": "Red flag.", "kind": "judgment", "rule_spec": None},
    {
        "id": "c2",
        "text": "Conservative therapy.",
        "kind": "rule",
        "rule_spec": {"kind": "conservative_therapy", "codes": ["97110"], "min_duration_days": 28},
    },
]


def _bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {"resource": {"resourceType": "Patient", "id": "pat-1", "birthDate": "1960-01-01"}},
            {
                "resource": {
                    "resourceType": "Procedure",
                    "id": "p-1",
                    "subject": {"reference": "Patient/pat-1"},
                    "performedDateTime": "2020-09-01T00:00:00Z",
                    "code": {"coding": [{"code": "97110"}]},
                }
            },
        ],
    }


@pytest_asyncio.fixture
async def deps() -> AsyncIterator[ActivityDeps]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory: async_sessionmaker[AsyncSession] = make_session_factory(engine)
    async with factory() as s:
        await load_bundle(s, _bundle(), clinic_id="clinic-a")
        await s.commit()

    async def get_version(payer: str, procedure: str, as_of: str) -> str | None:
        return "L34220"

    async def load_checklist(payer: str, procedure: str, version: str) -> list[dict[str, Any]]:
        return CHECKLIST

    client = httpx.AsyncClient()
    yield ActivityDeps(
        session_factory=factory,
        audit_log=AuditLog(),
        payer_client=client,
        get_version=get_version,
        load_checklist=load_checklist,
    )
    await client.aclose()
    await engine.dispose()


async def test_assess_activity_produces_decisions(deps: ActivityDeps) -> None:
    async def fake_complete(messages: Any, *, schema: Any, **kwargs: Any) -> Any:
        return _JudgeResult(status="not_met", confidence=0.6, rationale="no red flag")

    _set_complete_fn(fake_complete)
    set_activity_deps(deps)
    try:
        env = ActivityEnvironment()
        out = await env.run(
            assess_case,
            {
                "case_id": "case-1",
                "tenant_id": "clinic-a",
                "patient_id": "pat-1",
                "payer": "medicare",
                "procedure": "lumbar_spine_mri",
                "as_of": "2020-12-01",
            },
        )
    finally:
        _set_complete_fn(None)

    assert out["policy_version"] == "L34220"
    decisions = {d["criterion_id"]: d for d in out["decisions"]}
    assert decisions["c2"]["status"] == "met" and decisions["c2"]["method"] == "rule"
    assert decisions["c1"]["method"] == "agent"
