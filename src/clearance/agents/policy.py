"""Policy node (plan T5.3): return the criteria checklist for the selected
policy version. Runs in parallel with the evidence node."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentcore.guardrails import guarded

# (payer, procedure, version) -> list of Criterion dicts (ground truth).
ChecklistLoader = Callable[[str, str, str], Awaitable[list[dict[str, Any]]]]

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def make_policy_node(load_checklist: ChecklistLoader) -> NodeFn:
    @guarded("policy")
    async def policy(state: dict[str, Any]) -> dict[str, Any]:
        criteria = await load_checklist(
            state["payer"], state["procedure"], state.get("policy_version") or ""
        )
        if not criteria:
            return {"errors": ["empty checklist for policy version"], "degraded": True}
        return {"checklist": criteria}

    return policy
