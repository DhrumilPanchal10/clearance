"""Intake node (plan T5.2): normalize payer/procedure and select the policy
version in force on the case date."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentcore.guardrails import guarded

# (payer, procedure, as_of) -> policy version in force, or None.
PolicyVersionLookup = Callable[[str, str, str], Awaitable[str | None]]

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def make_intake_node(get_policy_version: PolicyVersionLookup) -> NodeFn:
    @guarded("intake")
    async def intake(state: dict[str, Any]) -> dict[str, Any]:
        payer = str(state["payer"]).strip().lower()
        procedure = str(state["procedure"]).strip().lower()
        version = await get_policy_version(payer, procedure, state["as_of"])
        if version is None:
            return {
                "errors": [f"no policy version for {payer}/{procedure} as_of {state['as_of']}"],
                "degraded": True,
            }
        return {"payer": payer, "procedure": procedure, "policy_version": version}

    return intake
