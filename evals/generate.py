"""Generate labelled eval cases from the real checklists (plan T9.1).

For each procedure we load the authored ground-truth checklist and, for each
rule criterion, synthesise chart facts that make the rule evaluate to a chosen
label (met / not_met), plus a few cases with a missing fact (age unknown) that a
simulated clinician must fill. Judgment criteria get an assigned oracle label.

Because the facts are built directly from each rule's own code set and
thresholds, the expected labels are correct by construction — no hand-labelling.
Run: ``python -m evals.generate`` → writes ``evals/cases/*.yaml``.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any

from clearance.policies.checklist import load_checklist
from clearance.policies.rules import _months_before
from evals.schema import CASES_DIR, EvalCase, FactResource, save_case

PROCEDURES = ["lumbar_spine_mri", "knee_mri", "ct_abdomen"]
PAYER = "medicare"
AS_OF = "2020-12-01"
_ASOF_D = date.fromisoformat(AS_OF)
PARSED = {
    "lumbar_spine_mri": "data/policies/parsed/lumbar_spine_mri.json",
    "knee_mri": "data/policies/parsed/knee_mri.json",
    "ct_abdomen": "data/policies/parsed/ct_abdomen.json",
}


def _rid(prefix: str, n: int) -> str:
    return f"{prefix}-{n:04d}"


def _satisfy_rule(
    spec: dict[str, Any], target: str, seq: int
) -> tuple[dict[str, list[FactResource]], str | None]:
    """Return (resources-by-bucket, birth_date) that make ``spec`` → ``target``.

    ``target`` is "met" or "not_met". A None birth_date leaves age unknown.
    """
    kind = spec.get("kind")
    out: dict[str, list[FactResource]] = {"conditions": [], "procedures": [], "medications": []}
    birth: str | None = None

    if kind == "age":
        lo = spec.get("min_years") or 0
        hi = spec.get("max_years") or (lo + 40)
        if target == "met":
            age = (lo + hi) // 2 if spec.get("max_years") else lo + 5
        else:
            age = (spec.get("min_years") or 1) - 1  # below minimum
        birth = date(_ASOF_D.year - age, 6, 1).isoformat()
        return out, birth

    if kind == "diagnosis":
        codes = spec.get("any_of", [])
        absent = spec.get("must_be_absent", False)
        present = (target == "met") != absent  # met⊕absent decides presence
        if present and codes:
            out["conditions"].append(
                FactResource(_rid("cond", seq), [codes[0]], (_ASOF_D - timedelta(days=90)).isoformat())
            )
        return out, birth

    if kind == "prior_procedure":
        codes = spec.get("codes", [])
        months = spec.get("within_months", 12)
        absent = spec.get("must_be_absent", False)
        present = (target == "met") != absent
        if present and codes:
            in_window = _months_before(_ASOF_D, max(1, months - 1))
            out["procedures"].append(
                FactResource(_rid("proc", seq), [codes[0]], in_window.isoformat())
            )
        return out, birth

    if kind == "conservative_therapy":
        codes = spec.get("codes", [])
        days = spec.get("min_duration_days", 28)
        if target == "met" and codes:
            start = (_ASOF_D - timedelta(days=days + 14)).isoformat()
            out["procedures"].append(FactResource(_rid("ct", seq), [codes[0]], start))
        elif target == "not_met" and codes:
            start = (_ASOF_D - timedelta(days=max(1, days - 14))).isoformat()  # too recent
            out["procedures"].append(FactResource(_rid("ct", seq), [codes[0]], start))
        return out, birth

    return out, birth


def _merge(dst: dict[str, list[FactResource]], src: dict[str, list[FactResource]]) -> None:
    for k in dst:
        dst[k].extend(src.get(k, []))


def _build_case(
    procedure: str, criteria: list[Any], plan: dict[str, str], n: int, tag: str
) -> EvalCase:
    """plan maps criterion_id -> target label (met/not_met/unknown)."""
    buckets: dict[str, list[FactResource]] = {"conditions": [], "procedures": [], "medications": []}
    birth = date(_ASOF_D.year - 55, 6, 1).isoformat()  # sensible default age
    expected: dict[str, str] = {}
    hidden: dict[str, Any] = {}

    for crit in criteria:
        cid = crit.id
        target = plan.get(cid, "met")
        if crit.kind == "rule":
            spec = crit.rule_spec or {}
            if target == "unknown" and spec.get("kind") == "age":
                birth = None  # hide age; clinician will supply it (resolves to met)
                hidden[cid] = {"birth_date": date(_ASOF_D.year - 60, 1, 1).isoformat()}
                expected[cid] = "met"
                continue
            res, b = _satisfy_rule(spec, "not_met" if target == "not_met" else "met", n)
            _merge(buckets, res)
            if b is not None:
                birth = b
            expected[cid] = "not_met" if target == "not_met" else "met"
        else:
            if target == "unknown":
                # The chart can't resolve it → the clinician does. Expected FINAL
                # label is met; the oracle returns unknown (keyed on hidden_facts)
                # so the gap-fill loop is exercised end-to-end.
                hidden[cid] = {"answer": "confirmed on review"}
                expected[cid] = "met"
            else:
                expected[cid] = target  # judgment oracle label

    # End state (post gap-fill): any not_met → not_met; any true unknown →
    # needs_clinician; else approved.
    labels = set(expected.values())
    if "unknown" in labels:
        end = "needs_clinician"
    elif "not_met" in labels:
        end = "not_met"
    else:
        end = "approved"

    return EvalCase(
        case_id=f"{procedure}-{n:03d}",
        payer=PAYER,
        procedure=procedure,
        as_of=AS_OF,
        birth_date=birth,
        conditions=buckets["conditions"],
        procedures=buckets["procedures"],
        medications=buckets["medications"],
        hidden_facts=hidden,
        expected_labels=expected,
        expected_end_state=end,
        tags=[tag],
    )


def generate(cases_dir: Path = CASES_DIR) -> int:
    n = 0
    for procedure in PROCEDURES:
        checklist = load_checklist(PARSED[procedure])
        crits = checklist.criteria
        ids = [c.id for c in crits]

        # 1) All-met "clean approval" cases.
        for _ in range(10):
            n += 1
            save_case(_build_case(procedure, crits, {cid: "met" for cid in ids}, n, "clean_approve"), cases_dir)

        # 2) One criterion failing at a time (isolates each rule/judgment).
        for cid in ids:
            n += 1
            plan = {x: "met" for x in ids}
            plan[cid] = "not_met"
            save_case(_build_case(procedure, crits, plan, n, "single_fail"), cases_dir)

        # 2b) Pairs of criteria failing together (harder; stresses aggregation).
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                n += 1
                plan = {x: "met" for x in ids}
                plan[ids[i]] = "not_met"
                plan[ids[j]] = "not_met"
                save_case(_build_case(procedure, crits, plan, n, "double_fail"), cases_dir)

        # 3) Clinician-gap cases: hide age (if an age rule exists) else a judgment.
        age_ids = [c.id for c in crits if c.kind == "rule" and (c.rule_spec or {}).get("kind") == "age"]
        gap_ids = age_ids or [c.id for c in crits if c.kind != "rule"][:1]
        for gid in gap_ids:
            n += 1
            plan = {x: "met" for x in ids}
            plan[gid] = "unknown"
            save_case(_build_case(procedure, crits, plan, n, "clinician_gap"), cases_dir)

    return n


if __name__ == "__main__":
    count = generate()
    print(f"Generated {count} eval cases in evals/cases")
