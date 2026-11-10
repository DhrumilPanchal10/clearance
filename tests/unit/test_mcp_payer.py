"""Tests for the payer MCP write tool (T4.4)."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from payer_service.app import app

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from clearance.mcp_servers.base import PermissionDenied, ToolContext
from clearance.mcp_servers.payer import ApprovalRequired, build_payer_tools, idempotency_key


def _ctx(role: str = "coordinator", clinic: str = "clinic-a") -> ToolContext:
    return ToolContext(
        claims=UserClaims(user_id="u1", tenant_id=clinic, role=role, raw={}), clinic_id=clinic
    )


@pytest_asyncio.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://payer") as c:
        await c.post("/_control/reset")
        await c.post("/_control/labels", json={"case-1": {"outcome": "approved"}})
        yield c


def test_idempotency_key_is_stable_per_attempt() -> None:
    assert idempotency_key("case-1", 1) == idempotency_key("case-1", 1)
    assert idempotency_key("case-1", 1) != idempotency_key("case-1", 2)


async def test_submit_requires_approval_token(client: httpx.AsyncClient) -> None:
    tools = build_payer_tools(client, AuditLog())
    with pytest.raises(ApprovalRequired):
        await tools.submit_prior_auth(
            _ctx(), case_id="case-1", procedure="lumbar_spine_mri", packet={}, approval_token=""
        )


async def test_submit_succeeds_with_approval(client: httpx.AsyncClient) -> None:
    tools = build_payer_tools(client, AuditLog())
    res = await tools.submit_prior_auth(
        _ctx(), case_id="case-1", procedure="lumbar_spine_mri", packet={}, approval_token="ok"
    )
    assert res["status"] == "approved"


async def test_submit_is_exactly_once_on_retry(client: httpx.AsyncClient) -> None:
    tools = build_payer_tools(client, AuditLog())
    first = await tools.submit_prior_auth(
        _ctx(),
        case_id="case-1",
        procedure="lumbar_spine_mri",
        packet={},
        approval_token="ok",
        attempt=1,
    )
    # Same case + attempt => same idempotency key => replayed, not duplicated.
    again = await tools.submit_prior_auth(
        _ctx(),
        case_id="case-1",
        procedure="lumbar_spine_mri",
        packet={},
        approval_token="ok",
        attempt=1,
    )
    assert first["claim_id"] == again["claim_id"]
    assert again["idempotent_replay"] is True


async def test_status_roundtrip(client: httpx.AsyncClient) -> None:
    tools = build_payer_tools(client, AuditLog())
    claim = (
        await tools.submit_prior_auth(
            _ctx(), case_id="case-1", procedure="lumbar_spine_mri", packet={}, approval_token="ok"
        )
    )["claim_id"]
    status = await tools.get_status(_ctx(role="clinician"), claim_id=claim)
    assert status["status"] == "approved"


async def test_clinician_cannot_submit(client: httpx.AsyncClient) -> None:
    tools = build_payer_tools(client, AuditLog())
    with pytest.raises(PermissionDenied):
        await tools.submit_prior_auth(
            _ctx(role="clinician"),
            case_id="case-1",
            procedure="lumbar_spine_mri",
            packet={},
            approval_token="ok",
        )
