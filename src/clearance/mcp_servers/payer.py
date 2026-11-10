"""payer MCP server (plan T4.4).

The only *write* tool in the system: it submits a prior-auth packet to the payer
service. Two guarantees beyond the base guard:

- **Human-in-the-loop:** submission requires a non-empty ``approval_token`` (a
  coordinator's approval). No token → no submission.
- **Exactly-once:** the idempotency key is ``hash(case_id, attempt)``, so a
  retried attempt reuses the same key and the payer replays the first decision
  instead of creating a duplicate claim.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import httpx

from agentcore.audit import AuditLog
from clearance.mcp_servers.base import MCPError, Risk, ToolContext, mcp_tool

_SUBMIT_ROLES = frozenset({"coordinator", "manager"})
_STATUS_ROLES = frozenset({"coordinator", "clinician", "manager"})


class ApprovalRequired(MCPError):
    """Raised when a submission is attempted without a human approval token."""


def idempotency_key(case_id: str, attempt: int) -> str:
    return hashlib.sha256(f"{case_id}:{attempt}".encode()).hexdigest()


def build_payer_tools(client: httpx.AsyncClient, audit_log: AuditLog) -> SimpleNamespace:
    @mcp_tool(
        "submit_prior_auth", allowed_roles=_SUBMIT_ROLES, risk=Risk.WRITE, audit_log=audit_log
    )
    async def submit_prior_auth(
        ctx: ToolContext,
        *,
        case_id: str,
        procedure: str,
        packet: dict[str, Any],
        approval_token: str,
        attempt: int = 1,
        callback_url: str | None = None,
    ) -> dict[str, Any]:
        if not approval_token:
            raise ApprovalRequired("submission requires a coordinator approval_token")
        resp = await client.post(
            "/claims/prior-auth",
            headers={"Idempotency-Key": idempotency_key(case_id, attempt)},
            json={
                "case_id": case_id,
                "procedure": procedure,
                "packet": packet,
                "callback_url": callback_url,
            },
        )
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    @mcp_tool("get_status", allowed_roles=_STATUS_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def get_status(ctx: ToolContext, *, claim_id: str) -> dict[str, Any]:
        resp = await client.get(f"/status/{claim_id}")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    return SimpleNamespace(submit_prior_auth=submit_prior_auth, get_status=get_status)
