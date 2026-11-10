"""Human-in-the-loop routing policy (plan T7.2).

Two rules the platform enforces:

1. **Every submission needs a coordinator's approval** — enforced structurally
   by the payer write tool (no ``approval_token`` → no submission) and by the
   orchestration gate. This module does not relax that.
2. **Escalate to a manager** when a case is risky: low model confidence, high
   projected cost, or a second (or later) denial. Manager-queued cases wait for
   a manager decision instead of a coordinator one.

Coordinator/manager overrides (approve something the agent judged not-met, or
reject something it judged met, or edit the letter) are captured as labelled
examples so Phase 9 can learn from real human corrections.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

# Thresholds (kept here, not scattered). Confidence is the min across criteria
# decided by the agent (rule decisions are confidence 1.0).
LOW_CONFIDENCE = 0.75
HIGH_COST_USD = 0.08
SECOND_DENIAL = 1  # appeal_cycles >= 1 means we've already been denied once

OVERRIDES_PATH = Path("data/overrides/overrides.jsonl")

ManagerReason = Literal["low_confidence", "high_cost", "repeat_denial"]


@dataclass
class RouteDecision:
    """Where a case goes for human review and why."""

    assigned_role: str  # "coordinator" | "manager"
    needs_manager: bool
    reasons: list[ManagerReason] = field(default_factory=list)


def min_agent_confidence(decisions: list[dict[str, Any]]) -> float:
    """Lowest confidence among agent-decided criteria; 1.0 if all rule-based."""
    agent = [d.get("confidence", 1.0) for d in decisions if d.get("method") == "agent"]
    return min(agent) if agent else 1.0


def route_for_review(
    *,
    decisions: list[dict[str, Any]],
    est_cost_usd: float,
    appeal_cycles: int,
) -> RouteDecision:
    """Decide coordinator vs. manager review for a case about to be approved."""
    reasons: list[ManagerReason] = []
    if min_agent_confidence(decisions) < LOW_CONFIDENCE:
        reasons.append("low_confidence")
    if est_cost_usd > HIGH_COST_USD:
        reasons.append("high_cost")
    if appeal_cycles >= SECOND_DENIAL:
        reasons.append("repeat_denial")
    needs_manager = bool(reasons)
    return RouteDecision(
        assigned_role="manager" if needs_manager else "coordinator",
        needs_manager=needs_manager,
        reasons=reasons,
    )


@dataclass
class Override:
    """A human decision that departed from (or edited) the agent's output."""

    case_id: str
    tenant_id: str
    payer: str
    procedure: str
    actor_role: str
    action: str  # approve | reject | edit_letter
    agent_verdict: str | None
    agent_decisions: list[dict[str, Any]]
    note: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_eval_record(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "tenant_id": self.tenant_id,
            "payer": self.payer,
            "procedure": self.procedure,
            "actor_role": self.actor_role,
            "action": self.action,
            "agent_verdict": self.agent_verdict,
            "agent_decisions": self.agent_decisions,
            "note": self.note,
            "at": self.at,
            "label_source": "human_override",
        }


def record_override(override: Override, path: Path = OVERRIDES_PATH) -> None:
    """Append one override as a JSONL eval example (best-effort, never raises)."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(override.as_eval_record()) + "\n")
    except OSError:  # pragma: no cover - disk issues must not break the request
        pass
