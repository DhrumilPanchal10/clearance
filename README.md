# Clearance

**Durable, evidence-cited prior-authorization automation.** Clearance turns a
prior-auth request into a durable, auditable case: it reads the patient chart
(synthetic FHIR R4), pulls the payer's in-force coverage policy, decides each
criterion (**rules in Python, judgment by agents**), drafts a letter of medical
necessity where **every clinical claim cites a FHIR resource id**, routes it for
human approval, submits to a simulated payer, and tracks the outcome — surviving
worker restarts, payer outages, and appeals via a Temporal workflow.

> **Run it in two commands** (no database, payer, or cloud needed):
> ```bash
> make demo-api     # backend on :8080, seeds ~7 live sample cases
> make web          # the UI on :3000  →  switch roles, approve a case
> ```

---

## The problem

Prior authorization is where care stalls: a coordinator re-reads a payer policy,
hunts the chart for the facts that match each criterion, writes a justification
letter, submits to a portal, and babysits the result for days — per request,
thousands of times a month. It's slow, error-prone, and the "AI" temptation is to
let a model free-wheel over the chart and hallucinate medical necessity.

Clearance takes the opposite stance: **the quantitative, rule-checkable parts are
decided in code and cited to the chart; the model is reserved for genuine
judgment; and a human signs off before anything reaches the payer.**

## Results vs. a single-agent baseline

Same judgment oracle for both systems, so the gap is purely architectural —
rules-in-code + per-criterion citations vs. an LLM reasoning over the chart.
Generated from `evals/` (57 labelled cases, OFFLINE, deterministic):

| Metric | **Clearance** | Baseline | 
| --- | --- | --- |
| Case pass@1 (all criteria + end state) | **100%** | 21% |
| Case pass^3 (stable across 3 runs) | **100%** | 21% |
| Per-criterion accuracy | **100%** | 78.5% |
| Citation precision (claims resolving to a real resource) | **100%** | 0% |
| Cost per case (vs. one strong-model agent) | **−98%** | — |

- **Durability:** exactly-once submission held across **280 injected faults**
  (duplicate submits, payer 500/503/429, duplicate + out-of-order webhooks).
- **Retrieval:** policy RAG recall@3 = 100%, evidence precision/recall = 100% vs.
  the rules-engine ground truth.

Full reports: [`docs/results/summary.md`](docs/results/summary.md) ·
[`cost.md`](docs/results/cost.md) · [`retrieval.md`](docs/results/retrieval.md).

**Why the baseline loses:** it decides on presence-of-code and misses the
quantitative and negation logic (age ranges, date windows, therapy-duration
thresholds, "no contraindication"), and it asserts medical necessity with no
citation. Clearance decides those in a deterministic engine and cites the exact
resource it used.

## Architecture

Temporal **outside** (one durable `PriorAuthCase` workflow per case), LangGraph
**inside** each stage. Tools are reachable only through MCP servers (RBAC +
audit + clinic scoping); every LLM call goes through `agentcore/llm.py`.

```mermaid
flowchart LR
  UI[Next.js UI<br/>coordinator · clinician · manager] -->|REST + SSE| API[FastAPI<br/>RBAC, HITL, webhooks]
  API --> WF[Temporal: PriorAuthCase]
  subgraph WF stages — each a Temporal activity running a LangGraph sub-graph
    A[intake] --> B[evidence ∥ policy] --> C[criteria] --> D[draft] --> V[verify] --> S[submit] --> T[track] --> AP[appeal]
  end
  C -.rules in Python / judgment via LLM.-> C
  WF --> MCP[MCP servers<br/>fhir_read · policy_search · payer · documents]
  MCP --> PG[(Postgres + pgvector<br/>FHIR jsonb · policies · audit · RLS per clinic)]
  S --> PAY[Payer service<br/>scriptable faults]
  WF --> MEM[(Episodic memory<br/>per-payer playbooks)]
  API -.OpenTelemetry.-> OTel[Langfuse / Phoenix]
```

The **in-process `CaseService`** mirrors the workflow's state machine so the API,
the UI, and the offline tests run with no Temporal server; production swaps in
the Temporal-backed path at the deps layer.

## Production spine checklist

| Concern | How |
| --- | --- |
| Durability | Temporal workflow; Continue-As-New bounds appeal history; timers for human waits |
| Exactly-once writes | Payer tool idempotency key = `hash(case_id, attempt)`; 4xx non-retryable |
| Human-in-the-loop | No submission without a coordinator token; manager escalation on low confidence / high cost / repeat denial |
| Determinism | Rule-checkable criteria decided in Python, never a model |
| Grounding | Every clinical claim cites a FHIR id; verifier gate blocks uncited claims |
| Guardrails | `@guarded` nodes: budget, loop, wall-clock, prompt-injection screens |
| Security | Postgres RLS per clinic; PHI redaction in logs/traces; untrusted-note screening |
| Cost | Tiered routing, evidence-card compression, cached stable prefixes |
| Observability | OpenTelemetry spans per stage/tool/LLM call; Temporal Web UI |
| Memory | Episodic per-payer playbooks, expiring on policy-version change |

## Evaluation method

Cases (`evals/cases/*.yaml`) are generated from the real CMS/Medicare ground-truth
checklists; facts are synthesised from each rule's own code set and thresholds,
so expected labels are **correct by construction** (no hand-labelling). The
system under test is the production assess graph + the cited-letter drafter; a
simulated clinician answers gap-fill questions only from each case's hidden
facts; the citation judge is resolver-based (a claim is supported iff it cites a
FHIR id that resolves to a real chart resource). See
[`docs/results/judge_calibration.md`](docs/results/judge_calibration.md).

## Security & data

Synthetic (Synthea) health data only, with HIPAA-style controls regardless:
minimum-necessary retrieval (ages, not names; no MRN), PHI redaction before any
log line or exported trace, clinic row-level isolation, an audit record of every
read and write, and clinical note text treated as untrusted input (injection
screening + neutralization). See [`docs/threat-model.md`](docs/threat-model.md).

## Quickstart

```bash
make install        # uv sync (deps + dev)
make test           # OFFLINE=1 pytest — 238 tests, no API keys needed
make lint           # ruff + mypy --strict

# Zero-infra demo (no Postgres/payer/Temporal):
make demo-api       # :8080
make web            # :3000

# Full stack (Postgres + Redis + Temporal + api/worker/payer/web):
docker compose -f docker-compose.full.yml up --build

# Reproduce the numbers:
python -m evals.run           # headline results → docs/results/summary.md
python -m evals.cost          # cost analysis    → docs/results/cost.md
python -m evals.retrieval_eval # retrieval        → docs/results/retrieval.md
```

`OFFLINE=1` uses recorded fixtures / deterministic stubs, so tests and CI run
with no keys.

## Decisions & trade-offs

- **Rules in code, not prompts.** Rule-checkable criteria are deterministic and
  auditable; the LLM is a liability there, so it's reserved for judgment. This is
  the single biggest driver of both accuracy and cost.
- **Temporal outside, LangGraph inside.** Durability and human waits belong to a
  workflow engine; multi-step reasoning belongs to a graph. Keeping them separate
  keeps workflow code deterministic (all I/O in activities).
- **In-process backend mirror.** So the whole product is runnable and testable
  offline, which is also how the eval stays honest and reproducible.
- **Offline-first retrieval.** Pure-Python BM25 + hashing embeddings run with no
  downloads; bge-small + pgvector plug in behind the same interface for prod.
- **Honest IaC.** Terraform targets LocalStack by default; compute is referenced,
  not a bill waiting to happen.

## Roadmap

More payers and procedures (beyond Medicare × imaging trio); a model-based
citation judge calibrated against the resolver baseline; live bge-small/pgvector
retrieval benchmarks; and a hosted demo on a single small VM with the Temporal
dev server.

---

See [`plan.md`](plan.md) for the full build plan and [`PROGRESS.md`](PROGRESS.md)
for the task-by-task log.
