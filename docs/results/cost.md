# Clearance — Cost & Performance

_Transparent estimate: token heuristic (~4 chars/token) × representative per-tier prices (`agentcore/prices.py`). Relative reductions are the point; absolute spend comes from billed usage on `RunCost`._

Averaged across the three M1 procedures:

| Configuration | LLM calls/case | Input tokens/case | $/case | vs baseline |
| --- | --- | --- | --- | --- |
| Baseline (single strong agent) | 3 | 18,200 | $0.01140 | −0% |
| + Routing (rules in code) | 2 | 10,920 | $0.00684 | −40% |
| + Compression (evidence cards) | 2 | 7,410 | $0.00079 | −93% |
| + Prompt caching (stable prefix) | 2 | 7,410 | $0.00025 | −98% |

**Net: −98% cost per case** vs a single strong-model agent, while *improving* accuracy (see `summary.md`).

### Levers
- **Routing** removes the LLM entirely from rule-checkable criteria — the majority of each checklist — and reserves the strong tier for genuine judgment.
- **Compression** swaps raw chart notes for a compact, cited evidence card in the judgment prompt.
- **Caching** keeps the policy + system prompt as a stable prefix so it is billed once per case at the cached rate, not per criterion.

Assumptions: policy ≈ 3500 tok, raw notes ≈ 1800 tok, evidence card ≈ 45 tok.

