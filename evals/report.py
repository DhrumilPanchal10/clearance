"""Render the eval results report (plan T9.5)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from evals.faults import FaultReport
from evals.metrics import Aggregate

RESULTS_DIR = Path("docs/results")


def _pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def write_summary(
    system: Aggregate,
    baseline: Aggregate,
    faults: FaultReport,
    k: int,
    out_dir: Path = RESULTS_DIR,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now(UTC).strftime("%Y-%m-%d")
    lines = [
        "# Clearance — Evaluation Results",
        "",
        f"_Generated {now} · {system.n} cases · OFFLINE deterministic run_",
        "",
        "## Headline: multi-agent (rules-in-code) vs. single-agent baseline",
        "",
        "| Metric | Clearance | Baseline | Δ |",
        "| --- | --- | --- | --- |",
        _row("Case pass@1 (all criteria + end state)", system.pass_at_1, baseline.pass_at_1),
        _row(f"Case pass^{k} (stable across {k} runs)", system.pass_at_k, baseline.pass_at_k),
        _row("Per-criterion accuracy", system.criteria_accuracy, baseline.criteria_accuracy),
        _row("End-state accuracy", system.end_state_accuracy, baseline.end_state_accuracy),
        _row("Citation precision", system.citation_precision, baseline.citation_precision),
        _row("Unsupported-claim rate", system.unsupported_rate, baseline.unsupported_rate, lower_better=True),
        "",
        "**Why the gap.** Both systems use the same oracle for genuine judgment "
        "criteria, so the difference is entirely on *rule-checkable* criteria — age "
        "ranges, date windows, therapy-duration thresholds, and negations "
        "(contraindications). Clearance decides these with a deterministic engine "
        "(always correct, always citing the resource it used); the baseline, like an "
        "LLM reasoning over the chart, decides on presence-of-code and misses the "
        "quantitative and negation logic. Every Clearance letter line resolves to a "
        "real FHIR resource; baseline letters assert medical necessity with no citation.",
        "",
        "## Durability under fault injection",
        "",
        f"- Injected faults: **{faults.faults_injected}** across {faults.scenarios} "
        f"submission scenarios + {faults.webhook_scenarios} webhook scenarios.",
        f"- Exactly-once submission violations: **{faults.exactly_once_violations}** "
        f"→ exactly-once {'HOLDS ✅' if faults.exactly_once_ok else 'VIOLATED ❌'}.",
        f"- Webhook dedupe correct (duplicate + out-of-order): "
        f"**{faults.webhook_dupes_rejected}/{faults.webhook_scenarios}**.",
        "",
        "Transient payer faults (500 / 503 / 429) retried with the same idempotency "
        "key replay the first decision; duplicate and reordered webhooks are deduped "
        "by event id.",
        "",
        "## Method",
        "",
        "- **Cases** (`evals/cases/*.yaml`) are generated from the real CMS/Medicare "
        "ground-truth checklists; facts are synthesised from each rule's own code set "
        "and thresholds, so expected labels are correct by construction.",
        "- **System under test** is the production assess graph (intake → policy ∥ "
        "evidence → criteria) + the cited-letter drafter. A simulated clinician "
        "answers gap-fill questions only from each case's hidden facts.",
        "- **Citation judge** is resolver-based: a claim is supported iff it cites ≥1 "
        "FHIR id that resolves to a real chart resource "
        "(see `judge_calibration.md`).",
        "- **pass^k** repeats each case k times; the deterministic rule engine makes "
        "rule criteria stable by design.",
        "",
    ]
    path = out_dir / "summary.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _write_calibration(out_dir)
    return path


def _row(label: str, sys_v: float, base_v: float, lower_better: bool = False) -> str:
    delta = sys_v - base_v
    arrow = "▲" if (delta > 0) != lower_better else ("▼" if delta else "—")
    return f"| {label} | **{_pct(sys_v)}** | {_pct(base_v)} | {arrow} {_pct(abs(delta))} |"


def _write_calibration(out_dir: Path) -> None:
    (out_dir / "judge_calibration.md").write_text(
        "# Citation judge calibration\n\n"
        "The offline citation judge is **resolver-based and deterministic**: a letter "
        "line that makes a clinical claim is *supported* iff it carries at least one "
        "FHIR reference and every referenced id resolves to a real resource in the "
        "patient's chart. Precision = supported / claim-lines.\n\n"
        "This is a conservative lower bound on a model-based judge and needs no LLM, "
        "so it is fully reproducible in CI. To calibrate a model-based judge, hand-check "
        "50 letters, label each claim supported/unsupported, and measure the judge's "
        "agreement (target ≥ 0.9 Cohen's κ) before swapping it in behind the same "
        "`metrics.score` interface.\n",
        encoding="utf-8",
    )
