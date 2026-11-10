"""Decompose a coverage policy into a criteria checklist (plan T1.3).

A model drafts the decomposition from policy text; a human then reviews and
corrects every checklist by hand — the corrected checklists are ground truth for
evaluation, so this module only produces *drafts*. Rule criteria carry a
``rule_spec`` that must parse as a T1.4 RuleSpec, which is validated in Python.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from agentcore.cost import RunCost
from agentcore.llm import complete
from clearance.policies.rules import parse_rule_spec

CriterionKind = Literal["rule", "judgment"]


class ChecklistError(ValueError):
    """Raised when a drafted/corrected checklist is structurally invalid."""


class Criterion(BaseModel):
    """One atomic coverage requirement extracted from a policy."""

    id: str
    text: str
    kind: CriterionKind
    # Present iff kind == "rule"; a JSON RuleSpec (see policies.rules).
    rule_spec: dict[str, Any] | None = None
    # The policy sentence the criterion came from, to aid human review + citation.
    source_quote: str = ""


class Checklist(BaseModel):
    payer: str
    procedure: str
    version: str
    criteria: list[Criterion]


# --- LLM draft schemas (the model fills these) ------------------------------ #


class _CriterionDraft(BaseModel):
    text: str
    kind: CriterionKind
    rule_spec: dict[str, Any] | None = None
    source_quote: str = Field(default="")


class _ChecklistDraft(BaseModel):
    criteria: list[_CriterionDraft]


_SYSTEM = (
    "You decompose a Medicare coverage policy into atomic, checkable criteria for "
    "prior authorization. For each distinct coverage requirement emit one criterion:\n"
    "- text: the requirement in one sentence.\n"
    "- kind: 'rule' if it can be decided mechanically from structured chart data "
    "(patient age, diagnosis codes, a prior procedure within N months, or duration "
    "of conservative therapy); otherwise 'judgment'.\n"
    "- rule_spec: for 'rule' criteria ONLY, a JSON object matching one of:\n"
    '  {"kind":"age","min_years":int?,"max_years":int?}\n'
    '  {"kind":"diagnosis","any_of":[icd10_or_snomed_codes]}\n'
    '  {"kind":"prior_procedure","codes":[cpt],"within_months":int,"must_be_absent":bool}\n'
    '  {"kind":"conservative_therapy","codes":[rxnorm_or_cpt],"min_duration_days":int}\n'
    "- source_quote: the sentence(s) in the policy the criterion is based on.\n"
    "Do not invent codes you cannot ground in the policy text; prefer 'judgment' "
    "when unsure. Return every requirement you find."
)


def _user_prompt(policy_text: str, procedure: str) -> str:
    return f"Procedure: {procedure}\n\nPolicy text:\n\n{policy_text}"


def _criterion_id(payer: str, procedure: str, version: str, n: int) -> str:
    return f"{payer}:{procedure}:{version}:c{n}"


async def decompose_policy(
    policy_text: str,
    *,
    payer: str,
    procedure: str,
    version: str,
    run_cost: RunCost | None = None,
) -> Checklist:
    """Draft a checklist from policy text. Judgment criteria are kept as-is; rule
    criteria have their rule_spec validated against the T1.4 schema."""
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": _user_prompt(policy_text, procedure)},
    ]
    draft: _ChecklistDraft = await complete(
        messages, schema=_ChecklistDraft, model_tier="strong", run_cost=run_cost
    )

    criteria: list[Criterion] = []
    for n, item in enumerate(draft.criteria, start=1):
        if item.kind == "rule":
            if item.rule_spec is None:
                raise ChecklistError(f"rule criterion {n} missing rule_spec")
            parse_rule_spec(item.rule_spec)  # raises if the spec is malformed
        criteria.append(
            Criterion(
                id=_criterion_id(payer, procedure, version, n),
                text=item.text,
                kind=item.kind,
                rule_spec=item.rule_spec if item.kind == "rule" else None,
                source_quote=item.source_quote,
            )
        )
    return Checklist(payer=payer, procedure=procedure, version=version, criteria=criteria)


def validate_checklist(checklist: Checklist) -> list[str]:
    """Return a list of problems with a (possibly hand-corrected) checklist.

    Empty list means the checklist is structurally sound and every rule criterion
    has a parseable rule_spec. Used to keep ground-truth files honest.
    """
    problems: list[str] = []
    seen: set[str] = set()
    for c in checklist.criteria:
        if c.id in seen:
            problems.append(f"duplicate criterion id: {c.id}")
        seen.add(c.id)
        if c.kind == "rule":
            if c.rule_spec is None:
                problems.append(f"{c.id}: rule criterion has no rule_spec")
                continue
            try:
                parse_rule_spec(c.rule_spec)
            except Exception as exc:  # noqa: BLE001 — surface any parse failure
                problems.append(f"{c.id}: invalid rule_spec ({exc})")
        elif c.rule_spec is not None:
            problems.append(f"{c.id}: judgment criterion must not carry a rule_spec")
    return problems


def save_checklist(checklist: Checklist, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(checklist.model_dump(), indent=2))
    return p


def load_checklist(path: str | Path) -> Checklist:
    return Checklist.model_validate_json(Path(path).read_text())
