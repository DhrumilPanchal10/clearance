"""policy_search MCP server (plan T4.3).

Tools: get_policy, search_policy. Policies are public (not PHI), but access is
still audited and the effective-date filter is applied inside the query so the
version in force on the case date is the one returned.
"""

from __future__ import annotations

import re
from datetime import date
from types import SimpleNamespace
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentcore.audit import AuditLog
from clearance.mcp_servers.base import Risk, ToolContext, mcp_tool
from clearance.policies.versions import get_policy as _get_policy_row

# Policies carry no PHI, so every clinic role (incl. auditor) may read them.
_READ_ROLES = frozenset({"coordinator", "clinician", "manager", "auditor"})


def build_policy_search_tools(
    session_factory: async_sessionmaker[AsyncSession], audit_log: AuditLog
) -> SimpleNamespace:
    @mcp_tool("get_policy", allowed_roles=_READ_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def get_policy(
        ctx: ToolContext, *, payer: str, procedure: str, as_of: str
    ) -> dict[str, Any] | None:
        when = date.fromisoformat(as_of)
        async with session_factory() as s:
            row = await _get_policy_row(s, payer, procedure, when)
        if row is None:
            return None
        return {
            "payer": row.payer,
            "procedure": row.procedure,
            "version": row.version,
            "effective_from": row.effective_from.isoformat(),
            "effective_to": row.effective_to.isoformat() if row.effective_to else None,
            "source_url": row.source_url,
            "text": row.text,
        }

    @mcp_tool("search_policy", allowed_roles=_READ_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def search_policy(
        ctx: ToolContext,
        *,
        query: str,
        payer: str,
        procedure: str,
        as_of: str,
        max_snippets: int = 5,
    ) -> list[dict[str, Any]]:
        """Return policy passages matching ``query`` in the in-force version.

        Keyword snippet search; hybrid semantic retrieval is Phase 2 (T2.1).
        """
        when = date.fromisoformat(as_of)
        async with session_factory() as s:
            row = await _get_policy_row(s, payer, procedure, when)
        if row is None:
            return []
        snippets: list[dict[str, Any]] = []
        needle = query.lower()
        for para in re.split(r"\n\s*\n", row.text):
            if needle in para.lower():
                snippets.append({"version": row.version, "snippet": para.strip()[:500]})
                if len(snippets) >= max_snippets:
                    break
        return snippets

    return SimpleNamespace(get_policy=get_policy, search_policy=search_policy)
