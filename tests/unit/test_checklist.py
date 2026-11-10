"""Tests for clearance/policies/checklist.py (T1.3 machinery).

The LLM is stubbed via agentcore.llm._set_complete_fn, so these run offline with
no fixtures or keys.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from agentcore.llm import _set_complete_fn
from clearance.policies.checklist import (
    Checklist,
    ChecklistError,
    Criterion,
    _ChecklistDraft,
    _CriterionDraft,
    decompose_policy,
    load_checklist,
    save_checklist,
    validate_checklist,
)
from clearance.policies.rules import PatientFacts, evaluate, parse_rule_spec


@pytest.fixture
def stub_llm() -> AsyncIterator[Callable[[list[_CriterionDraft]], None]]:
    """Let a test set the drafted criteria the stubbed LLM will 'return'."""
    holder: dict[str, list[_CriterionDraft]] = {"criteria": []}

    async def _fake_complete(messages: Any, *, schema: Any, **kwargs: Any) -> Any:
        return _ChecklistDraft(criteria=holder["criteria"])

    _set_complete_fn(_fake_complete)

    def _set(criteria: list[_CriterionDraft]) -> None:
        holder["criteria"] = criteria

    try:
        yield _set
    finally:
        _set_complete_fn(None)


async def test_decompose_assigns_ids_and_separates_kinds(
    stub_llm: Callable[[list[_CriterionDraft]], None],
) -> None:
    stub_llm(
        [
            _CriterionDraft(
                text="Patient is at least 18.",
                kind="rule",
                rule_spec={"kind": "age", "min_years": 18},
                source_quote="Members aged 18 and older...",
            ),
            _CriterionDraft(
                text="Imaging is clinically appropriate per ordering physician.",
                kind="judgment",
                source_quote="...when clinically indicated.",
            ),
        ]
    )
    cl = await decompose_policy(
        "policy text", payer="medicare", procedure="lumbar_spine_mri", version="L37281"
    )
    assert [c.id for c in cl.criteria] == [
        "medicare:lumbar_spine_mri:L37281:c1",
        "medicare:lumbar_spine_mri:L37281:c2",
    ]
    assert cl.criteria[0].kind == "rule" and cl.criteria[0].rule_spec is not None
    # Judgment criteria never carry a rule_spec.
    assert cl.criteria[1].kind == "judgment" and cl.criteria[1].rule_spec is None


async def test_decompose_rejects_rule_without_spec(
    stub_llm: Callable[[list[_CriterionDraft]], None],
) -> None:
    stub_llm([_CriterionDraft(text="age rule", kind="rule", rule_spec=None)])
    with pytest.raises(ChecklistError):
        await decompose_policy("p", payer="medicare", procedure="x", version="v1")


async def test_decompose_rejects_malformed_rule_spec(
    stub_llm: Callable[[list[_CriterionDraft]], None],
) -> None:
    stub_llm([_CriterionDraft(text="bad", kind="rule", rule_spec={"kind": "not_a_rule"})])
    with pytest.raises(Exception):  # noqa: B017 — pydantic validation error
        await decompose_policy("p", payer="medicare", procedure="x", version="v1")


def test_validate_checklist_flags_problems() -> None:
    bad = Checklist(
        payer="medicare",
        procedure="x",
        version="v1",
        criteria=[
            Criterion(id="dup", text="a", kind="judgment"),
            Criterion(id="dup", text="b", kind="rule", rule_spec={"kind": "age"}),
            Criterion(id="c3", text="c", kind="rule", rule_spec=None),
            Criterion(id="c4", text="d", kind="judgment", rule_spec={"kind": "age"}),
            Criterion(id="c5", text="e", kind="rule", rule_spec={"kind": "bogus"}),
        ],
    )
    problems = validate_checklist(bad)
    assert any("duplicate" in p for p in problems)
    assert any("no rule_spec" in p for p in problems)
    assert any("must not carry" in p for p in problems)
    assert any("invalid rule_spec" in p for p in problems)


def test_validate_checklist_clean() -> None:
    ok = Checklist(
        payer="medicare",
        procedure="lumbar_spine_mri",
        version="L37281",
        criteria=[
            Criterion(id="c1", text="18+", kind="rule", rule_spec={"kind": "age", "min_years": 18}),
            Criterion(id="c2", text="appropriate", kind="judgment"),
        ],
    )
    assert validate_checklist(ok) == []


def test_save_load_roundtrip(tmp_path: Path) -> None:
    cl = Checklist(
        payer="medicare",
        procedure="lumbar_spine_mri",
        version="L37281",
        criteria=[
            Criterion(id="c1", text="18+", kind="rule", rule_spec={"kind": "age", "min_years": 18})
        ],
    )
    path = save_checklist(cl, tmp_path / "lumbar.json")
    assert load_checklist(path) == cl


def test_rule_criterion_feeds_t14_evaluator() -> None:
    """A rule criterion's spec must be directly evaluable by the T1.4 engine."""
    crit = Criterion(id="c1", text="18+", kind="rule", rule_spec={"kind": "age", "min_years": 18})
    assert crit.rule_spec is not None
    spec = parse_rule_spec(crit.rule_spec)
    facts = PatientFacts(as_of=date(2023, 1, 1), birth_date=date(1990, 1, 1))
    assert evaluate(spec, facts).status == "met"
