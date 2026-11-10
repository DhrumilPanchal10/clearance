"""Eval-suite CI gate (plan T9.5).

Runs the offline subset and asserts the quality thresholds that guard against
regressions: the multi-agent system is near-perfect on criteria + citations,
it beats the naive baseline, and exactly-once holds under fault injection.
"""

from __future__ import annotations

import pytest
from evals.harness import run_baseline, run_system
from evals.metrics import score
from evals.schema import load_cases


@pytest.mark.asyncio
async def test_cases_exist() -> None:
    cases = load_cases()
    assert len(cases) >= 50, "expected a populated eval case suite"


@pytest.mark.asyncio
async def test_system_beats_baseline_and_hits_thresholds() -> None:
    cases = load_cases()[::2]  # subset for speed
    sys_correct = sys_total = cite_ok = cite_total = sys_pass = 0
    base_pass = 0
    for case in cases:
        s = score(case, await run_system(case))
        sys_correct += s.criteria_correct
        sys_total += s.criteria_total
        cite_ok += s.supported_lines
        cite_total += s.claim_lines
        sys_pass += int(s.all_criteria_correct and s.end_state_correct)

        b = score(case, await run_baseline(case))
        base_pass += int(b.all_criteria_correct and b.end_state_correct)

    assert sys_correct / sys_total >= 0.99  # criteria accuracy
    assert cite_total > 0 and cite_ok / cite_total >= 0.99  # citation precision
    assert sys_pass > base_pass  # system beats the baseline


@pytest.mark.asyncio
async def test_exactly_once_under_faults() -> None:
    from evals.faults import run_fault_suite

    report = await run_fault_suite(n_cases=6)
    assert report.exactly_once_ok
    assert report.faults_injected > 0
    assert report.webhook_dupes_rejected == report.webhook_scenarios
