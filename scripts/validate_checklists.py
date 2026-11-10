"""Validate the ground-truth checklist files (plan T1.3).

Loads every data/policies/parsed/*.json checklist and runs validate_checklist,
reporting problems. Keeps hand-authored ground truth structurally honest.

    uv run python -m scripts.validate_checklists
"""

from __future__ import annotations

import sys
from pathlib import Path

from clearance.policies.checklist import load_checklist, validate_checklist

PARSED = Path("data/policies/parsed")


def main() -> int:
    files = sorted(PARSED.glob("*.json"))
    if not files:
        print("no checklist files found")
        return 1
    total_problems = 0
    for f in files:
        checklist = load_checklist(f)
        problems = validate_checklist(checklist)
        total_problems += len(problems)
        rules = sum(1 for c in checklist.criteria if c.kind == "rule")
        judgments = sum(1 for c in checklist.criteria if c.kind == "judgment")
        status = "OK" if not problems else f"{len(problems)} PROBLEM(S)"
        print(
            f"{f.name:26s} {checklist.procedure:18s} "
            f"criteria={len(checklist.criteria)} (rule={rules}, judgment={judgments}) [{status}]"
        )
        for p in problems:
            print(f"    - {p}")
    return 0 if total_problems == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
