"""Supervisor (plan T5.8): wire dependencies and assemble the three sub-graphs.

assess_graph  — intake -> (evidence ∥ policy) -> criteria
draft_graph   — submission -> verifier -> revise (≤2)
appeal_graph  — appeals

Production loaders read the ground-truth checklists and the in-force policy
version; tests can inject their own loaders.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentcore.audit import AuditLog
from clearance.agents.appeals import make_appeals_node
from clearance.agents.criteria import make_criteria_node
from clearance.agents.evidence import make_evidence_node
from clearance.agents.graphs import build_appeal_graph, build_assess_graph, build_draft_graph
from clearance.agents.intake import make_intake_node
from clearance.agents.policy import make_policy_node
from clearance.agents.submission import make_submission_node
from clearance.agents.verifier import make_verifier_node
from clearance.mcp_servers.fhir_read import build_fhir_read_tools
from clearance.policies.checklist import load_checklist as _load_checklist_file
from clearance.policies.versions import get_policy as _get_policy_row

PolicyVersionLookup = Callable[[str, str, str], Awaitable[str | None]]
ChecklistLoader = Callable[[str, str, str], Awaitable[list[dict[str, Any]]]]

PARSED_DIR = Path("data/policies/parsed")


def make_checklist_loader(parsed_dir: Path = PARSED_DIR) -> ChecklistLoader:
    async def load(payer: str, procedure: str, version: str) -> list[dict[str, Any]]:
        path = parsed_dir / f"{procedure}.json"
        if not path.exists():
            return []
        checklist = _load_checklist_file(path)
        return [c.model_dump() for c in checklist.criteria]

    return load


def make_policy_version_lookup(
    session_factory: async_sessionmaker[AsyncSession],
) -> PolicyVersionLookup:
    async def lookup(payer: str, procedure: str, as_of: str) -> str | None:
        async with session_factory() as s:
            row = await _get_policy_row(s, payer, procedure, date.fromisoformat(as_of))
        return row.version if row else None

    return lookup


def build_assess(
    session_factory: async_sessionmaker[AsyncSession],
    audit_log: AuditLog,
    get_version: PolicyVersionLookup,
    load_checklist: ChecklistLoader,
) -> Any:
    fhir_tools = build_fhir_read_tools(session_factory, audit_log)
    return build_assess_graph(
        make_intake_node(get_version),
        make_policy_node(load_checklist),
        make_evidence_node(fhir_tools, load_checklist),
        make_criteria_node(fhir_tools),
    )


def build_draft() -> Any:
    return build_draft_graph(make_submission_node(), make_verifier_node())


def build_appeal() -> Any:
    return build_appeal_graph(make_appeals_node())
