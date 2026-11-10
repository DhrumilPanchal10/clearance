# Clearance — Evaluation Results

_Generated 2026-11-10 · 57 cases · OFFLINE deterministic run_

## Headline: multi-agent (rules-in-code) vs. single-agent baseline

| Metric | Clearance | Baseline | Δ |
| --- | --- | --- | --- |
| Case pass@1 (all criteria + end state) | **100.0%** | 21.1% | ▲ 78.9% |
| Case pass^3 (stable across 3 runs) | **100.0%** | 21.1% | ▲ 78.9% |
| Per-criterion accuracy | **100.0%** | 78.5% | ▲ 21.5% |
| End-state accuracy | **100.0%** | 56.1% | ▲ 43.9% |
| Citation precision | **100.0%** | 0.0% | ▲ 100.0% |
| Unsupported-claim rate | **0.0%** | 100.0% | ▲ 100.0% |

**Why the gap.** Both systems use the same oracle for genuine judgment criteria, so the difference is entirely on *rule-checkable* criteria — age ranges, date windows, therapy-duration thresholds, and negations (contraindications). Clearance decides these with a deterministic engine (always correct, always citing the resource it used); the baseline, like an LLM reasoning over the chart, decides on presence-of-code and misses the quantitative and negation logic. Every Clearance letter line resolves to a real FHIR resource; baseline letters assert medical necessity with no citation.

## Durability under fault injection

- Injected faults: **280** across 80 submission scenarios + 40 webhook scenarios.
- Exactly-once submission violations: **0** → exactly-once HOLDS ✅.
- Webhook dedupe correct (duplicate + out-of-order): **40/40**.

Transient payer faults (500 / 503 / 429) retried with the same idempotency key replay the first decision; duplicate and reordered webhooks are deduped by event id.

## Method

- **Cases** (`evals/cases/*.yaml`) are generated from the real CMS/Medicare ground-truth checklists; facts are synthesised from each rule's own code set and thresholds, so expected labels are correct by construction.
- **System under test** is the production assess graph (intake → policy ∥ evidence → criteria) + the cited-letter drafter. A simulated clinician answers gap-fill questions only from each case's hidden facts.
- **Citation judge** is resolver-based: a claim is supported iff it cites ≥1 FHIR id that resolves to a real chart resource (see `judge_calibration.md`).
- **pass^k** repeats each case k times; the deterministic rule engine makes rule criteria stable by design.

