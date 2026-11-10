"""Eval runner CLI (plan T9.2/T9.5).

    python -m evals.run            # full suite + write docs/results/summary.md
    python -m evals.run --smoke    # fast offline subset (CI gate)

Runs every case through the production multi-agent graph and the naive baseline,
scores criteria accuracy / end-state / citations, computes pass@1 and pass^k,
runs the fault-injection suite, and (full mode) writes the results report.
"""

from __future__ import annotations

import argparse
import asyncio

from evals.faults import FaultReport, run_fault_suite
from evals.generate import generate
from evals.harness import run_baseline, run_system
from evals.metrics import Aggregate, score
from evals.report import write_summary
from evals.schema import load_cases

DEFAULT_K = 3


async def _run(smoke: bool) -> tuple[Aggregate, Aggregate, FaultReport, int]:
    cases = load_cases()
    if not cases:
        generate()
        cases = load_cases()
    if smoke:
        cases = cases[:: max(1, len(cases) // 30)][:30]
    k = 1 if smoke else DEFAULT_K

    system = Aggregate()
    baseline = Aggregate()
    for case in cases:
        # pass^k: repeat and require every run to pass.
        runs = [await run_system(case) for _ in range(k)]
        scores = [score(case, r) for r in runs]
        passed_all_k = all(s.all_criteria_correct and s.end_state_correct for s in scores)
        system.add(scores[0], passed_all_k)

        b = score(case, await run_baseline(case))
        baseline.add(b, b.all_criteria_correct and b.end_state_correct)

    faults = await run_fault_suite(n_cases=10 if smoke else 40)
    return system, baseline, faults, k


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="fast CI subset")
    args = ap.parse_args()

    system, baseline, faults, k = asyncio.run(_run(args.smoke))

    print(f"\nCases: {system.n}  (k={k})")
    print(f"  pass@1   system={system.pass_at_1:.1%}  baseline={baseline.pass_at_1:.1%}")
    print(f"  pass^{k}   system={system.pass_at_k:.1%}  baseline={baseline.pass_at_k:.1%}")
    print(f"  criteria system={system.criteria_accuracy:.1%}  baseline={baseline.criteria_accuracy:.1%}")
    print(f"  citation system={system.citation_precision:.1%}  baseline={baseline.citation_precision:.1%}")
    print(f"  faults injected={faults.faults_injected}  exactly_once_ok={faults.exactly_once_ok}")

    # CI gate thresholds.
    assert system.criteria_accuracy >= 0.99, "criteria accuracy regressed"
    assert system.citation_precision >= 0.99, "citation precision regressed"
    assert system.pass_at_1 > baseline.pass_at_1, "system must beat baseline"
    assert faults.exactly_once_ok, "exactly-once violated"

    if not args.smoke:
        path = write_summary(system, baseline, faults, k)
        print(f"\nWrote {path}")


if __name__ == "__main__":
    main()
