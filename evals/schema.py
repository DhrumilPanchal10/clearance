"""Eval case schema + YAML persistence (plan T9.1).

An :class:`EvalCase` fully specifies one labelled scenario: the patient's chart
facts, any facts hidden from the chart but known to a simulated clinician, the
expected per-criterion labels, and the expected end state. Cases are generated
(``evals.generate``) from the real ground-truth checklists so their labels are
by-construction correct, then persisted to ``evals/cases/*.yaml``.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

CASES_DIR = Path("evals/cases")


@dataclass
class FactResource:
    """A minimal FHIR resource: id, codes, optional date (ISO)."""

    id: str
    codes: list[str] = field(default_factory=list)
    date: str | None = None


@dataclass
class EvalCase:
    case_id: str
    payer: str
    procedure: str
    as_of: str
    # Chart facts the agent can see.
    birth_date: str | None
    conditions: list[FactResource] = field(default_factory=list)
    procedures: list[FactResource] = field(default_factory=list)
    medications: list[FactResource] = field(default_factory=list)
    # Facts NOT in the chart, revealed only when the clinician is asked.
    hidden_facts: dict[str, Any] = field(default_factory=dict)
    # Ground truth.
    expected_labels: dict[str, str] = field(default_factory=dict)  # criterion_id -> met/not_met/unknown
    expected_end_state: str = "approved"  # approved | not_met | needs_clinician | denied
    tags: list[str] = field(default_factory=list)

    def facts_payload(self) -> dict[str, Any]:
        """The shape ``get_patient_facts`` returns, for a fake tool to serve."""
        return {
            "birth_date": self.birth_date,
            "conditions": [asdict(c) for c in self.conditions],
            "procedures": [asdict(p) for p in self.procedures],
            "medications": [asdict(m) for m in self.medications],
        }


def _to_resources(items: list[dict[str, Any]]) -> list[FactResource]:
    return [FactResource(**i) for i in items]


def save_case(case: EvalCase, cases_dir: Path = CASES_DIR) -> Path:
    cases_dir.mkdir(parents=True, exist_ok=True)
    path = cases_dir / f"{case.case_id}.yaml"
    path.write_text(yaml.safe_dump(asdict(case), sort_keys=False), encoding="utf-8")
    return path


def load_case(path: Path) -> EvalCase:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    raw["conditions"] = _to_resources(raw.get("conditions", []))
    raw["procedures"] = _to_resources(raw.get("procedures", []))
    raw["medications"] = _to_resources(raw.get("medications", []))
    return EvalCase(**raw)


def load_cases(cases_dir: Path = CASES_DIR) -> list[EvalCase]:
    if not cases_dir.exists():
        return []
    return [load_case(p) for p in sorted(cases_dir.glob("*.yaml"))]
