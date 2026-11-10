"""Verifier node (plan T5.6): citation gate + criteria consistency.

Verdict:
- ``escalate`` — a criterion is not_met/unknown (policy not satisfied), or an
  uncited clinical claim remains after the revision budget: a human must decide.
- ``revise`` — the letter has uncited clinical lines but revisions remain.
- ``pass``   — every criterion met and every clinical line cited.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from agentcore.guardrails import MAX_REVISIONS, guarded
from clearance.mcp_servers.documents import LetterDraft, cited_refs, uncited_lines

NodeFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]


def make_verifier_node() -> NodeFn:
    @guarded("verifier")
    async def verifier(state: dict[str, Any]) -> dict[str, Any]:
        issues: list[str] = []

        decisions = state.get("decisions", [])
        unmet = [d.criterion_id for d in decisions if d.status != "met"]
        if unmet:
            issues.append(f"criteria not met: {unmet}")

        letter = LetterDraft.model_validate(
            state.get(
                "letter",
                {"title": "", "payer": "", "procedure": "", "patient_ref": "", "sections": []},
            )
        )
        uncited = uncited_lines(letter)

        # Citation gate: every cited ref must be a known evidence ref.
        known_refs = {ref for d in decisions for ref in d.evidence_refs}
        dangling = sorted(cited_refs(letter) - known_refs)
        if dangling:
            issues.append(f"letter cites unknown refs: {dangling}")

        if uncited:
            issues.append(f"uncited clinical lines: {uncited}")

        if unmet:
            verdict = "escalate"
        elif uncited or dangling:
            verdict = "revise" if state.get("revision_count", 0) < MAX_REVISIONS else "escalate"
        else:
            verdict = "pass"

        return {"verdict": verdict, "errors": issues}

    return verifier
