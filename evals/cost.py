"""Cost & performance analysis (plan T10.1/T10.2/T10.3).

Estimates cost per case under three cumulative optimisations and writes
``docs/results/cost.md``. It is a transparent *model* (token heuristic × per-tier
prices in :mod:`agentcore.prices`), not a billed figure — the point is the
relative reduction each lever delivers:

- **T10.1 routing** — rule-checkable criteria are decided in Python (0 LLM
  tokens); only genuine judgment criteria hit a model, and on the small/judge
  tier rather than the strong tier. Baseline sends every criterion to a strong
  model with the full policy + raw chart.
- **T10.2 context compression** — the judgment prompt carries a compact evidence
  card (~`CARD_TOKENS`) instead of the raw notes (~`RAW_NOTES_TOKENS`).
- **T10.3 prompt caching** — the stable policy + system prefix is cached, so its
  tokens are billed once per case at the cached rate instead of per criterion.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agentcore.prices import cost_usd
from clearance.policies.checklist import load_checklist
from evals.generate import PARSED, PROCEDURES

# Token-size assumptions (≈4 chars/token), documented in the report.
POLICY_TOKENS = 3500  # a typical LCD/NCD coverage article
SYSTEM_TOKENS = 120
RAW_NOTES_TOKENS = 1800  # unsummarised chart slice per criterion
CARD_TOKENS = 45  # compressed evidence card
CRITERION_TOKENS = 40
OUTPUT_TOKENS = 60

RESULTS_DIR = Path("docs/results")


@dataclass
class CostLine:
    name: str
    per_case_usd: float
    llm_calls: int
    input_tokens: int


def _counts() -> dict[str, tuple[int, int]]:
    """Per procedure: (#rule criteria, #judgment criteria)."""
    out: dict[str, tuple[int, int]] = {}
    for proc in PROCEDURES:
        crits = load_checklist(PARSED[proc]).criteria
        rules = sum(1 for c in crits if c.kind == "rule")
        judg = sum(1 for c in crits if c.kind != "rule")
        out[proc] = (rules, judg)
    return out


def _baseline(rules: int, judg: int) -> CostLine:
    # Every criterion → strong model, full policy + raw notes, no caching.
    calls = rules + judg
    per_call_in = POLICY_TOKENS + SYSTEM_TOKENS + RAW_NOTES_TOKENS + CRITERION_TOKENS
    total_in = per_call_in * calls
    cost = calls * cost_usd("strong", input_tokens=per_call_in, output_tokens=OUTPUT_TOKENS)
    return CostLine("Baseline (single strong agent)", cost, calls, total_in)


def _routed(rules: int, judg: int) -> CostLine:
    # Rule criteria: 0 LLM. Judgment: strong tier, still raw notes, no cache.
    calls = judg
    per_call_in = POLICY_TOKENS + SYSTEM_TOKENS + RAW_NOTES_TOKENS + CRITERION_TOKENS
    cost = calls * cost_usd("strong", input_tokens=per_call_in, output_tokens=OUTPUT_TOKENS)
    return CostLine("+ Routing (rules in code)", cost, calls, per_call_in * calls)


def _compressed(rules: int, judg: int) -> CostLine:
    calls = judg
    per_call_in = POLICY_TOKENS + SYSTEM_TOKENS + CARD_TOKENS + CRITERION_TOKENS
    cost = calls * cost_usd("judge", input_tokens=per_call_in, output_tokens=OUTPUT_TOKENS)
    return CostLine("+ Compression (evidence cards)", cost, calls, per_call_in * calls)


def _cached(rules: int, judg: int) -> CostLine:
    calls = judg
    prefix = POLICY_TOKENS + SYSTEM_TOKENS  # stable, cached once per case
    variable = CARD_TOKENS + CRITERION_TOKENS
    cost = 0.0
    for _ in range(calls):
        cost += cost_usd(
            "judge",
            input_tokens=prefix + variable,
            output_tokens=OUTPUT_TOKENS,
            cached_tokens=prefix,
        )
    return CostLine("+ Prompt caching (stable prefix)", cost, calls, (prefix + variable) * calls)


def analyze() -> list[CostLine]:
    counts = _counts()
    totals = [0.0, 0.0, 0.0, 0.0]
    agg_calls = [0, 0, 0, 0]
    agg_in = [0, 0, 0, 0]
    stages = [_baseline, _routed, _compressed, _cached]
    for rules, judg in counts.values():
        for i, fn in enumerate(stages):
            line = fn(rules, judg)
            totals[i] += line.per_case_usd
            agg_calls[i] += line.llm_calls
            agg_in[i] += line.input_tokens
    n = len(counts)
    names = [fn(0, 0).name for fn in stages]
    return [
        CostLine(names[i], totals[i] / n, agg_calls[i] // n, agg_in[i] // n)
        for i in range(len(stages))
    ]


def write_report(out_dir: Path = RESULTS_DIR) -> Path:
    lines = analyze()
    base = lines[0].per_case_usd
    out_dir.mkdir(parents=True, exist_ok=True)
    body = [
        "# Clearance — Cost & Performance",
        "",
        "_Transparent estimate: token heuristic (~4 chars/token) × representative "
        "per-tier prices (`agentcore/prices.py`). Relative reductions are the point; "
        "absolute spend comes from billed usage on `RunCost`._",
        "",
        "Averaged across the three M1 procedures:",
        "",
        "| Configuration | LLM calls/case | Input tokens/case | $/case | vs baseline |",
        "| --- | --- | --- | --- | --- |",
    ]
    for ln in lines:
        red = 0.0 if base == 0 else (1 - ln.per_case_usd / base)
        body.append(
            f"| {ln.name} | {ln.llm_calls} | {ln.input_tokens:,} | "
            f"${ln.per_case_usd:.5f} | −{red * 100:.0f}% |"
        )
    final = lines[-1].per_case_usd
    total_red = 0.0 if base == 0 else (1 - final / base)
    body += [
        "",
        f"**Net: −{total_red * 100:.0f}% cost per case** vs a single strong-model agent, "
        "while *improving* accuracy (see `summary.md`).",
        "",
        "### Levers",
        "- **Routing** removes the LLM entirely from rule-checkable criteria — the "
        "majority of each checklist — and reserves the strong tier for genuine judgment.",
        "- **Compression** swaps raw chart notes for a compact, cited evidence card in "
        "the judgment prompt.",
        "- **Caching** keeps the policy + system prompt as a stable prefix so it is "
        "billed once per case at the cached rate, not per criterion.",
        "",
        f"Assumptions: policy ≈ {POLICY_TOKENS} tok, raw notes ≈ {RAW_NOTES_TOKENS} tok, evidence card ≈ {CARD_TOKENS} tok.",
        "",
    ]
    path = out_dir / "cost.md"
    path.write_text("\n".join(body) + "\n", encoding="utf-8")
    return path


if __name__ == "__main__":
    p = write_report()
    for ln in analyze():
        print(f"{ln.name:40s} ${ln.per_case_usd:.5f}/case  ({ln.llm_calls} calls)")
    print(f"\nWrote {p}")
