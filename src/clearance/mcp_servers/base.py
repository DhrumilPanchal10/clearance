"""Base for Clearance MCP servers (plan T4.1).

Every tool is wrapped with the cross-cutting controls the plan requires: JWT-
derived identity, clinic scoping (minimum-necessary / no cross-clinic access),
RBAC per tool, an audit event, an OTel span, a timeout, a circuit breaker, and a
``risk`` label. Tool business logic stays small and policy-free; this layer
enforces the guarantees.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from functools import wraps
from typing import Any, TypeVar

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from agentcore.telemetry import span_tool

# Clearance clinic roles (must be a subset of agentcore.auth.ROLES).
CLINIC_ROLES: frozenset[str] = frozenset({"coordinator", "clinician", "manager", "auditor"})

T = TypeVar("T")


class Risk(StrEnum):
    READ = "read"
    WRITE = "write"


class MCPError(Exception):
    """Base class for MCP guard failures."""


class PermissionDenied(MCPError):
    pass


class ClinicScopeError(MCPError):
    pass


class CircuitOpen(MCPError):
    pass


class ToolTimeout(MCPError):
    pass


@dataclass(frozen=True)
class ToolContext:
    """Caller identity + the clinic the call targets.

    ``claims.tenant_id`` is the caller's clinic. ``clinic_id`` is the clinic the
    tool is being asked to act on; it must match, enforcing per-clinic isolation.
    """

    claims: UserClaims
    clinic_id: str

    @property
    def actor_id(self) -> str:
        return self.claims.user_id

    @property
    def caller_clinic(self) -> str:
        return self.claims.tenant_id


@dataclass
class CircuitBreaker:
    """Open after ``threshold`` consecutive failures; half-open after ``cooldown``."""

    threshold: int = 5
    cooldown_s: float = 30.0
    _failures: int = field(default=0)
    _opened_at: float | None = field(default=None)

    def before(self, *, now: float | None = None) -> None:
        if self._opened_at is None:
            return
        t = now if now is not None else time.monotonic()
        if t - self._opened_at < self.cooldown_s:
            raise CircuitOpen("circuit open")
        # cooldown elapsed → half-open: allow one trial call.
        self._opened_at = None

    def record_success(self) -> None:
        self._failures = 0
        self._opened_at = None

    def record_failure(self, *, now: float | None = None) -> None:
        self._failures += 1
        if self._failures >= self.threshold:
            self._opened_at = now if now is not None else time.monotonic()


def mcp_tool(
    name: str,
    *,
    allowed_roles: frozenset[str],
    risk: Risk,
    audit_log: AuditLog,
    timeout_s: float = 10.0,
    breaker: CircuitBreaker | None = None,
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Wrap an async tool fn ``(ctx: ToolContext, **kwargs) -> T`` with the guards."""
    cb = breaker or CircuitBreaker()

    def decorator(fn: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @wraps(fn)
        async def wrapper(ctx: ToolContext, **kwargs: Any) -> T:
            # RBAC per tool.
            if ctx.claims.role not in allowed_roles:
                raise PermissionDenied(f"role {ctx.claims.role!r} may not call {name!r}")
            # Clinic scoping: no cross-clinic access.
            if ctx.clinic_id != ctx.caller_clinic:
                raise ClinicScopeError(
                    f"caller clinic {ctx.caller_clinic!r} != target {ctx.clinic_id!r}"
                )
            cb.before()
            try:
                async with span_tool(name, tenant_id=ctx.clinic_id) as span:
                    span.set_attribute("clearance.tool.risk", risk.value)
                    span.set_attribute("clearance.actor_id", ctx.actor_id)
                    try:
                        result = await asyncio.wait_for(fn(ctx, **kwargs), timeout_s)
                    except TimeoutError as exc:
                        raise ToolTimeout(f"{name} exceeded {timeout_s}s") from exc
            except Exception:
                cb.record_failure()
                audit_log.append(
                    "mcp_tool_error",
                    actor_id=ctx.actor_id,
                    tenant_id=ctx.clinic_id,
                    payload={"tool": name, "risk": risk.value, "args": sorted(kwargs)},
                )
                raise
            cb.record_success()
            audit_log.append(
                "mcp_tool_call",
                actor_id=ctx.actor_id,
                tenant_id=ctx.clinic_id,
                payload={"tool": name, "risk": risk.value, "args": sorted(kwargs)},
            )
            return result

        wrapper.mcp_meta = {  # type: ignore[attr-defined]
            "name": name,
            "allowed_roles": allowed_roles,
            "risk": risk,
        }
        return wrapper

    return decorator
