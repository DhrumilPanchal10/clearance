"""In-memory case store + per-case event bus (plan T7.1).

The API keeps the authoritative orchestration state here. Each case has a
record (its current stage, decisions, draft, outcome) and an append-only event
log. SSE subscribers attach an async queue per case and receive every event
published after they subscribe, replayed from the start so a late client still
sees history.

This mirrors what the Temporal workflow holds durably; in-process it is the
backend that makes the whole system runnable and testable without a Temporal
server. Swapping to the Temporal-backed service is a drop-in at the deps layer.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat()


@dataclass
class TimelineEvent:
    """One observable thing that happened to a case."""

    seq: int
    at: str
    stage: str
    kind: str  # stage | decision | human | payer | error
    message: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class CaseRecord:
    """Everything the UI needs to render one case."""

    case_id: str
    tenant_id: str
    patient_id: str
    payer: str
    procedure: str
    as_of: str
    stage: str = "created"
    outcome: str | None = None
    verdict: str | None = None
    attempt: int = 0
    appeal_cycles: int = 0
    reminders: int = 0
    denial_reason: str | None = None
    claim_id: str | None = None
    confidence: float = 1.0
    est_cost_usd: float = 0.0
    needs_manager: bool = False
    manager_reasons: list[str] = field(default_factory=list)
    assigned_role: str = "coordinator"
    policy_version: str | None = None
    checklist: list[dict[str, Any]] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    evidence_cards: list[dict[str, Any]] = field(default_factory=list)
    letter: dict[str, Any] | None = None
    packet: dict[str, Any] | None = None
    clinician_questions: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_summary(self) -> dict[str, Any]:
        """The lighter shape the queue/list views render."""
        met = sum(1 for d in self.decisions if d.get("status") == "met")
        return {
            "case_id": self.case_id,
            "tenant_id": self.tenant_id,
            "patient_id": self.patient_id,
            "payer": self.payer,
            "procedure": self.procedure,
            "stage": self.stage,
            "outcome": self.outcome,
            "verdict": self.verdict,
            "confidence": round(self.confidence, 3),
            "est_cost_usd": round(self.est_cost_usd, 4),
            "needs_manager": self.needs_manager,
            "assigned_role": self.assigned_role,
            "criteria_total": len(self.decisions),
            "criteria_met": met,
            "appeal_cycles": self.appeal_cycles,
            "updated_at": self.updated_at,
            "created_at": self.created_at,
        }

    def to_detail(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    """Fan-out of per-case timeline events to live SSE subscribers."""

    def __init__(self) -> None:
        self._log: dict[str, list[TimelineEvent]] = defaultdict(list)
        self._subs: dict[str, set[asyncio.Queue[TimelineEvent]]] = defaultdict(set)
        self._seq: dict[str, int] = defaultdict(int)

    def publish(self, case_id: str, stage: str, kind: str, message: str, **data: Any) -> TimelineEvent:
        self._seq[case_id] += 1
        ev = TimelineEvent(
            seq=self._seq[case_id],
            at=_now(),
            stage=stage,
            kind=kind,
            message=message,
            data=dict(data),
        )
        self._log[case_id].append(ev)
        for q in list(self._subs.get(case_id, ())):
            q.put_nowait(ev)
        return ev

    def history(self, case_id: str) -> list[TimelineEvent]:
        return list(self._log.get(case_id, ()))

    def subscribe(self, case_id: str) -> asyncio.Queue[TimelineEvent]:
        q: asyncio.Queue[TimelineEvent] = asyncio.Queue()
        for ev in self._log.get(case_id, ()):  # replay history to late joiners
            q.put_nowait(ev)
        self._subs[case_id].add(q)
        return q

    def unsubscribe(self, case_id: str, q: asyncio.Queue[TimelineEvent]) -> None:
        self._subs.get(case_id, set()).discard(q)


class CaseStore:
    """Thread-free async-safe map of case_id -> CaseRecord."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}
        self._lock = asyncio.Lock()

    async def put(self, record: CaseRecord) -> None:
        async with self._lock:
            self._cases[record.case_id] = record

    def get(self, case_id: str) -> CaseRecord | None:
        return self._cases.get(case_id)

    def touch(self, case_id: str) -> None:
        rec = self._cases.get(case_id)
        if rec is not None:
            rec.updated_at = _now()

    def list(self) -> list[CaseRecord]:
        return sorted(self._cases.values(), key=lambda r: r.created_at, reverse=True)
