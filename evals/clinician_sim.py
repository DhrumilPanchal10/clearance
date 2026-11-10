"""Simulated clinician (plan T9.2).

Answers an agent's gap-fill question using ONLY the case's hidden facts — never
inventing anything. If the case has no hidden fact for a criterion, the clinician
cannot answer (returns None), which must leave the criterion unresolved.
"""

from __future__ import annotations

from typing import Any

from evals.schema import EvalCase


def answer(case: EvalCase, criterion_id: str) -> dict[str, Any] | None:
    return case.hidden_facts.get(criterion_id)
