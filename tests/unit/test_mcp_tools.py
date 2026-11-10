"""Tests for fhir_read (T4.2) and policy_search (T4.3) MCP tools."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from clearance.db import make_engine, make_session_factory
from clearance.fhir.loader import load_bundle
from clearance.mcp_servers.base import ToolContext
from clearance.mcp_servers.fhir_read import build_fhir_read_tools
from clearance.mcp_servers.policy_search import build_policy_search_tools
from clearance.models import Base
from clearance.policies.ingest import parse_policy_text, upsert_policy

PATIENT = "pat-001"


def _bundle(patient_id: str) -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": patient_id,
                    "birthDate": "1970-05-01",
                    "gender": "female",
                    "name": [{"family": "Private", "given": ["Name"]}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": f"{patient_id}-c1",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "onsetDateTime": "2019-01-01T00:00:00Z",
                    "code": {"coding": [{"code": "M54.5"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "DocumentReference",
                    "id": f"{patient_id}-d1",
                    "subject": {"reference": f"Patient/{patient_id}"},
                    "date": "2019-02-01T00:00:00Z",
                    "description": "Physical therapy progress note: 8 weeks completed.",
                }
            },
        ],
    }


POLICY = """---
payer: medicare
procedure: lumbar_spine_mri
version: L37281
effective_from: 2015-10-01
effective_to:
source_url: https://www.cms.gov/x
---
Coverage indications.

Lumbar MRI is covered after at least six weeks of conservative therapy.

Billing and coding details.
"""


def _ctx(clinic: str, role: str = "clinician") -> ToolContext:
    return ToolContext(
        claims=UserClaims(user_id="u1", tenant_id=clinic, role=role, raw={}), clinic_id=clinic
    )


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = make_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    f = make_session_factory(engine)
    async with f() as s:
        await load_bundle(s, _bundle(PATIENT), clinic_id="clinic-a")
        await load_bundle(s, _bundle("pat-b"), clinic_id="clinic-b")
        await upsert_policy(s, parse_policy_text(POLICY))
        await s.commit()
    yield f
    await engine.dispose()


# --- fhir_read -------------------------------------------------------------- #


async def test_patient_summary_minimum_necessary(factory: async_sessionmaker[AsyncSession]) -> None:
    tools = build_fhir_read_tools(factory, AuditLog())
    summary = await tools.get_patient_summary(_ctx("clinic-a"), patient_id=PATIENT)
    # Demographics are age + gender only — no name/address/MRN.
    assert set(summary["demographics"]) == {"age", "gender"}
    assert "Private" not in str(summary)
    assert summary["conditions"][0]["codes"] == ["M54.5"]


async def test_query_resources_filters_by_code(factory: async_sessionmaker[AsyncSession]) -> None:
    tools = build_fhir_read_tools(factory, AuditLog())
    hits = await tools.query_resources(
        _ctx("clinic-a"), patient_id=PATIENT, type="Condition", codes=["M54.5"]
    )
    assert len(hits) == 1 and hits[0]["id"] == f"{PATIENT}-c1"
    miss = await tools.query_resources(
        _ctx("clinic-a"), patient_id=PATIENT, type="Condition", codes=["Z00.0"]
    )
    assert miss == []


async def test_search_notes_keyword(factory: async_sessionmaker[AsyncSession]) -> None:
    tools = build_fhir_read_tools(factory, AuditLog())
    hits = await tools.search_notes(_ctx("clinic-a"), patient_id=PATIENT, query="conservative")
    assert hits == []  # phrase not present
    hits = await tools.search_notes(_ctx("clinic-a"), patient_id=PATIENT, query="therapy")
    assert len(hits) == 1


async def test_clinic_scoping_hides_other_clinic(factory: async_sessionmaker[AsyncSession]) -> None:
    tools = build_fhir_read_tools(factory, AuditLog())
    # clinic-a caller cannot see clinic-b's patient (same query, scoped out).
    summary = await tools.get_patient_summary(_ctx("clinic-a"), patient_id="pat-b")
    assert summary["conditions"] == []
    assert summary["demographics"] == {}


# --- policy_search ---------------------------------------------------------- #


async def test_get_policy_in_force(factory: async_sessionmaker[AsyncSession]) -> None:
    tools = build_policy_search_tools(factory, AuditLog())
    pol = await tools.get_policy(
        _ctx("clinic-a", role="coordinator"),
        payer="medicare",
        procedure="lumbar_spine_mri",
        as_of="2020-01-01",
    )
    assert pol is not None and pol["version"] == "L37281"


async def test_search_policy_snippet(factory: async_sessionmaker[AsyncSession]) -> None:
    tools = build_policy_search_tools(factory, AuditLog())
    snips = await tools.search_policy(
        _ctx("clinic-a", role="auditor"),
        query="conservative therapy",
        payer="medicare",
        procedure="lumbar_spine_mri",
        as_of="2020-01-01",
    )
    assert len(snips) == 1
    assert "conservative therapy" in snips[0]["snippet"].lower()
