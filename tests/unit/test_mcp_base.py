"""Tests for the MCP base guard layer (T4.1)."""

from __future__ import annotations

import asyncio

import pytest

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from clearance.mcp_servers.base import (
    CircuitBreaker,
    CircuitOpen,
    ClinicScopeError,
    PermissionDenied,
    Risk,
    ToolContext,
    ToolTimeout,
    mcp_tool,
)


def _ctx(
    role: str = "clinician", caller_clinic: str = "clinic-a", target: str = "clinic-a"
) -> ToolContext:
    return ToolContext(
        claims=UserClaims(user_id="u1", tenant_id=caller_clinic, role=role, raw={}),
        clinic_id=target,
    )


async def test_allowed_role_runs_and_audits() -> None:
    log = AuditLog()

    @mcp_tool("double", allowed_roles=frozenset({"clinician"}), risk=Risk.READ, audit_log=log)
    async def double(ctx: ToolContext, *, x: int) -> int:
        return x * 2

    assert await double(_ctx(), x=21) == 42
    entries = log.entries()
    assert len(entries) == 1
    assert entries[0].event_type == "mcp_tool_call"
    assert entries[0].payload["tool"] == "double"
    assert entries[0].tenant_id == "clinic-a"


async def test_disallowed_role_denied() -> None:
    log = AuditLog()

    @mcp_tool("w", allowed_roles=frozenset({"manager"}), risk=Risk.WRITE, audit_log=log)
    async def w(ctx: ToolContext) -> str:
        return "ok"

    with pytest.raises(PermissionDenied):
        await w(_ctx(role="clinician"))


async def test_cross_clinic_denied() -> None:
    log = AuditLog()

    @mcp_tool("r", allowed_roles=frozenset({"clinician"}), risk=Risk.READ, audit_log=log)
    async def r(ctx: ToolContext) -> str:
        return "ok"

    with pytest.raises(ClinicScopeError):
        await r(_ctx(caller_clinic="clinic-a", target="clinic-b"))


async def test_timeout_raises_and_audits_error() -> None:
    log = AuditLog()

    @mcp_tool(
        "slow",
        allowed_roles=frozenset({"clinician"}),
        risk=Risk.READ,
        audit_log=log,
        timeout_s=0.01,
    )
    async def slow(ctx: ToolContext) -> str:
        await asyncio.sleep(0.2)
        return "done"

    with pytest.raises(ToolTimeout):
        await slow(_ctx())
    assert log.entries()[-1].event_type == "mcp_tool_error"


async def test_circuit_opens_after_threshold() -> None:
    log = AuditLog()
    breaker = CircuitBreaker(threshold=2, cooldown_s=60)

    @mcp_tool(
        "boom",
        allowed_roles=frozenset({"clinician"}),
        risk=Risk.READ,
        audit_log=log,
        breaker=breaker,
    )
    async def boom(ctx: ToolContext) -> str:
        raise ValueError("nope")

    for _ in range(2):
        with pytest.raises(ValueError):
            await boom(_ctx())
    # Circuit now open: the next call short-circuits before the tool runs.
    with pytest.raises(CircuitOpen):
        await boom(_ctx())


def test_circuit_breaker_half_open_after_cooldown() -> None:
    cb = CircuitBreaker(threshold=1, cooldown_s=10)
    cb.record_failure(now=100.0)
    with pytest.raises(CircuitOpen):
        cb.before(now=105.0)  # still cooling down
    cb.before(now=111.0)  # cooldown elapsed → half-open, allowed
    cb.record_success()
    cb.before(now=112.0)  # closed again
