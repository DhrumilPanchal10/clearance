"""Retrieval-backed evidence cards (plan T2.2).

For each criterion, builds an :class:`EvidenceCard` from two sources:

1. **Structured FHIR query** — resources whose codes match the rule's code set,
   within the rule's date window. These are the citable ``fhir_refs``.
2. **Semantic note search** — hybrid retrieval over ``DocumentReference`` note
   text for the criterion, to surface supporting narrative. Note text is
   untrusted, so it is screened/neutralized before it informs the summary.

Cards are cached per ``(patient_id, criterion_id)`` so re-assessing a case (or
an appeal) doesn't re-retrieve. This is the richer T2.2 implementation that can
back the evidence node; the deterministic node remains the offline default.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from clearance.agents.state import EvidenceCard
from clearance.policies.rules import _months_before
from clearance.retrieval.hybrid import Document, HybridRetriever
from clearance.security.injection import screen_note


@dataclass
class Note:
    id: str
    text: str
    date: str | None = None


@dataclass
class ChartSlice:
    """Minimum-necessary chart inputs for card building."""

    as_of: str
    conditions: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    medications: list[dict[str, Any]] = field(default_factory=list)
    notes: list[Note] = field(default_factory=list)


def _spec_codes(spec: dict[str, Any]) -> set[str]:
    return set(spec.get("any_of") or spec.get("codes") or [])


def _buckets_for(kind: str, chart: ChartSlice) -> list[dict[str, Any]]:
    return {
        "diagnosis": chart.conditions,
        "prior_procedure": chart.procedures,
        "conservative_therapy": chart.procedures + chart.medications,
    }.get(kind, [])


def _in_window(item_date: str | None, spec: dict[str, Any], as_of: str) -> bool:
    months = spec.get("within_months")
    if not months or not item_date:
        return True
    try:
        d = date.fromisoformat(item_date[:10])
    except ValueError:
        return True
    return _months_before(date.fromisoformat(as_of), months) <= d <= date.fromisoformat(as_of)


class EvidenceCardBuilder:
    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], EvidenceCard] = {}

    def build(self, patient_id: str, criterion: dict[str, Any], chart: ChartSlice) -> EvidenceCard:
        key = (patient_id, criterion["id"])
        if key in self._cache:
            return self._cache[key]

        refs: list[str] = []
        note_support = 0
        if criterion.get("kind") == "rule":
            spec = criterion.get("rule_spec") or {}
            codes = _spec_codes(spec)
            kind = spec.get("kind", "")
            for item in _buckets_for(kind, chart):
                if codes & set(item.get("codes", [])) and _in_window(
                    item.get("date"), spec, chart.as_of
                ):
                    refs.append(item["id"])

        # Semantic note retrieval (narrative support; not a citation source).
        if chart.notes:
            retriever = HybridRetriever()
            retriever.index([Document(n.id, n.text, {"date": n.date}) for n in chart.notes])
            hits = retriever.search(criterion["text"], top_k=3)
            safe_hits = [h for h in hits if screen_note(h.text).safe]
            note_support = len(safe_hits)

        summary = _summarize(criterion, refs, note_support)
        card = EvidenceCard(criterion_id=criterion["id"], summary=summary, fhir_refs=refs)
        self._cache[key] = card
        return card


def _summarize(criterion: dict[str, Any], refs: list[str], note_support: int) -> str:
    if criterion.get("kind") != "rule":
        return (
            f"Narrative support from {note_support} chart note(s) relevant to "
            f"'{criterion['text']}'."
        )
    parts = [f"{len(refs)} structured resource(s) matched the rule code set."]
    if note_support:
        parts.append(f"{note_support} corroborating note(s).")
    return " ".join(parts)
