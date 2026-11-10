"""Episodic memory and per-payer playbooks (plan T7.4).

Every terminal payer outcome is written as an *episode*:
``(payer, procedure, outcome, denial_reason, policy_version)``. A nightly
consolidation rolls recent episodes into compact *playbook notes* — one per
``(payer, procedure)`` — that summarise what tends to get approved vs. denied
and why. Notes are stamped with the policy version they were learned under and
**expire when the policy version changes**, so stale guidance never leaks into a
case evaluated against a newer policy.

The supervisor retrieves the active note for a case before drafting/submitting,
so the agent can pre-empt the denial reasons seen most often for that payer.

Storage is a JSONL episode log plus a derived playbook file; both default under
``data/memory/`` and all I/O is best-effort (memory is an optimisation, never a
correctness dependency).
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MEMORY_DIR = Path("data/memory")
EPISODES_PATH = MEMORY_DIR / "episodes.jsonl"
PLAYBOOK_PATH = MEMORY_DIR / "playbook.json"

# How many recent episodes per (payer, procedure) feed a consolidation.
WINDOW = 50
# Minimum episodes before a note is emitted (avoid noise from one data point).
MIN_EPISODES = 3


@dataclass
class Episode:
    payer: str
    procedure: str
    outcome: str  # approved | denied | rejected
    denial_reason: str | None
    policy_version: str | None
    case_id: str = ""
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def key(self) -> tuple[str, str]:
        return (self.payer, self.procedure)


@dataclass
class PlaybookNote:
    payer: str
    procedure: str
    policy_version: str | None
    approvals: int
    denials: int
    top_denial_reasons: list[tuple[str, int]]
    guidance: str
    at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def key(self) -> str:
        return f"{self.payer}:{self.procedure}"


class EpisodicMemory:
    """Append-only episode log with a derived, version-expiring playbook."""

    def __init__(
        self,
        episodes_path: Path = EPISODES_PATH,
        playbook_path: Path = PLAYBOOK_PATH,
    ) -> None:
        self._episodes_path = episodes_path
        self._playbook_path = playbook_path

    # --- write path ------------------------------------------------------- #

    def record(self, episode: Episode) -> None:
        """Persist one outcome (best-effort)."""
        try:
            self._episodes_path.parent.mkdir(parents=True, exist_ok=True)
            with self._episodes_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(episode)) + "\n")
        except OSError:  # pragma: no cover
            pass

    def load_episodes(self) -> list[Episode]:
        if not self._episodes_path.exists():
            return []
        out: list[Episode] = []
        with self._episodes_path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                out.append(Episode(**json.loads(line)))
        return out

    # --- consolidation ---------------------------------------------------- #

    def consolidate(self) -> list[PlaybookNote]:
        """Roll episodes into playbook notes and persist them (nightly job)."""
        notes = consolidate(self.load_episodes())
        try:
            self._playbook_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {n.key(): asdict(n) for n in notes}
            self._playbook_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except OSError:  # pragma: no cover
            pass
        return notes

    def _load_playbook(self) -> dict[str, PlaybookNote]:
        if not self._playbook_path.exists():
            return {}
        raw = json.loads(self._playbook_path.read_text(encoding="utf-8"))
        out: dict[str, PlaybookNote] = {}
        for k, v in raw.items():
            v = dict(v)
            v["top_denial_reasons"] = [tuple(x) for x in v.get("top_denial_reasons", [])]
            out[k] = PlaybookNote(**v)
        return out

    # --- read path (supervisor retrieval) --------------------------------- #

    def get_note(
        self, payer: str, procedure: str, policy_version: str | None
    ) -> PlaybookNote | None:
        """Active note for this case, or None if absent or version-expired."""
        note = self._load_playbook().get(f"{payer}:{procedure}")
        if note is None:
            return None
        # Expire on policy version change: guidance learned under an older
        # policy must not steer a case evaluated against a newer one.
        if policy_version is not None and note.policy_version != policy_version:
            return None
        return note


def _guidance(approvals: int, denials: int, top: list[tuple[str, int]]) -> str:
    total = approvals + denials
    if total == 0:
        return "No prior outcomes recorded."
    rate = approvals / total
    if not top:
        return f"{approvals}/{total} approved ({rate:.0%}). No denial pattern yet."
    reason, count = top[0]
    pretty = reason.replace("_", " ")
    return (
        f"{approvals}/{total} approved ({rate:.0%}). Most common denial: "
        f"'{pretty}' ({count}×) — ensure that criterion is fully evidenced and cited "
        f"before submitting."
    )


def consolidate(episodes: list[Episode]) -> list[PlaybookNote]:
    """Pure consolidation: group by (payer, procedure), summarise the window.

    Only episodes sharing the group's *latest* policy version are counted, so a
    note always reflects the policy currently in force for that group.
    """
    groups: dict[tuple[str, str], list[Episode]] = {}
    for ep in episodes:
        groups.setdefault(ep.key(), []).append(ep)

    notes: list[PlaybookNote] = []
    for (payer, procedure), eps in groups.items():
        eps = eps[-WINDOW:]
        # Latest policy version seen for the group defines the active cohort.
        versions = [e.policy_version for e in eps if e.policy_version]
        latest = versions[-1] if versions else None
        cohort = [e for e in eps if e.policy_version == latest] if latest else eps
        if len(cohort) < MIN_EPISODES:
            continue
        approvals = sum(1 for e in cohort if e.outcome == "approved")
        denials = sum(1 for e in cohort if e.outcome == "denied")
        reasons = Counter(
            e.denial_reason for e in cohort if e.outcome == "denied" and e.denial_reason
        )
        top = reasons.most_common(3)
        notes.append(
            PlaybookNote(
                payer=payer,
                procedure=procedure,
                policy_version=latest,
                approvals=approvals,
                denials=denials,
                top_denial_reasons=top,
                guidance=_guidance(approvals, denials, top),
            )
        )
    return notes
