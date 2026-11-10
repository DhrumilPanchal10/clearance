# CLEARANCE — Implementation Plan

Durable prior-authorization automation platform. Single source of truth for Claude Code.

**How Claude Code uses this file:** read §0 and ONLY the assigned task (e.g. "T4.3"). When done: tick the checkbox, add one line to `PROGRESS.md`, commit.

---

## §0 — Rules for every coding agent

- Stack: Python 3.12, uv, FastAPI, Temporal Python SDK (`temporalio`), LangGraph, MCP Python SDK (FastMCP), LiteLLM, PostgreSQL + pgvector, Redis, OpenTelemetry, Next.js 15 + TypeScript.
- Zero-budget infra: Supabase Postgres, Upstash Redis (or local), Clerk auth, Langfuse cloud or local Phoenix, Gemini + Groq via LiteLLM, local embeddings/reranker, Temporal via `temporal server start-dev` (Temporal CLI).
- Machine: M1, 8 GB. Do NOT run a HAPI FHIR server. FHIR R4 resources are stored as JSONB in Postgres and served by our own read API.
- Health data is synthetic only (Synthea). Still apply HIPAA-style controls: minimum-necessary retrieval, PHI redaction in logs/traces, audit of every read and write.
- Temporal rules: workflow code is deterministic (no I/O, no random, no datetime.now — use `workflow.now()`); all LLM, DB and HTTP work happens in activities; use `workflow.patched()` / versioning for changes to running workflows.
- All LLM calls via `agentcore/llm.py`; all tools via MCP servers; every agent node wrapped by `@guarded`; Pydantic structured outputs only.
- Rule-checkable criteria (age, dates, codes, prior-treatment windows) are evaluated in Python, never by a model.
- Every clinical claim in generated text must cite a FHIR resource id; uncited claims block submission.
- `OFFLINE=1`: recorded LLM fixtures; tests and CI pass with no keys; missing fixture raises.
- Silent success is a bug: a case that ends without a terminal state must surface as failed.
- ruff + mypy --strict; pytest; do not edit files outside the task list without saying why; never commit secrets.

---

## §1 — Architecture (reference)

```
Next.js (coordinator / clinician / manager views) ──> FastAPI (JWT/RBAC)
        │ start case / send signals
        ▼
Temporal workflow  PriorAuthCase (one per case, runs for days)
  intake → [evidence ∥ policy] → criteria → (gaps? signal: clinician_answer, reminder timers)
  → draft → verify → (signal: coordinator_approval) → submit → track (webhook signal / timers)
  → approved | denied → appeal → verify → approval → resubmit
  each stage = Temporal activity running a LangGraph sub-graph of agents
        │
MCP servers: fhir_read · policy_search · payer · documents   (auth + audit)
        │
Postgres: fhir_resources(jsonb) · policies(versioned) · cases · memory · audit (RLS per clinic) · pgvector
Payer service (separate FastAPI app): submit / status / webhooks with injected failures
All hops → OpenTelemetry → Langfuse/Phoenix ; Temporal Web UI for workflow history
```

Repo layout:

```
clearance/
├── AGENTS.md CLAUDE.md plan.md PROGRESS.md README.md pyproject.toml Makefile docker-compose.yml .env.example
├── .github/workflows/ci.yml  .claude/commands/task.md
├── docs/ discovery.md threat-model.md architecture.md decisions/ results/
├── src/agentcore/             # same spine as other projects (copy if you already built it)
├── src/clearance/
│   ├── config.py db.py models.py
│   ├── fhir/ loader.py api.py evidence_cards.py
│   ├── policies/ ingest.py versions.py checklist.py rules.py
│   ├── retrieval/ chunking.py hybrid.py rerank.py
│   ├── mcp_servers/ fhir_read.py policy_search.py payer.py documents.py base.py
│   ├── agents/ state.py intake.py evidence.py policy.py submission.py appeals.py verifier.py supervisor.py graphs.py
│   ├── workflows/ prior_auth.py activities.py worker.py
│   ├── hitl/ policies.py queue.py
│   └── api/ main.py routes_cases.py routes_signals.py routes_webhooks.py sse.py
├── payer_service/ app.py failure_modes.py
├── apps/web/
├── evals/ cases/ clinician_sim.py run.py pass_k.py judge/ fault_injection.py report.py thresholds.yaml
├── data/ synthea/ policies/raw/ policies/parsed/
├── migrations/  scripts/  tests/
```

---

## §2 — Milestones

- **M1 Resume-ready slice:** Phases 0–7 for 1 payer × 3 procedures, 50 cases scored vs single-agent baseline (T9.1, T9.2).
- **M2 Interview-ready:** + full eval suite, fault injection, appeals, routing.
- **M3 Complete:** 3 payers × 6 procedures, 200 cases, full UI, deploy, docs, demo.

---

## Phase 0 — Foundation

- [x] **T0.1 Scaffold** · Claude Code · small — layout above; deps: fastapi, uvicorn, pydantic-settings, temporalio, langgraph, mcp, litellm, psycopg[binary], sqlalchemy, pgvector, redis, opentelemetry-sdk, opentelemetry-exporter-otlp, sentence-transformers, bm25s, fhir.resources, httpx, tenacity, pytest, pytest-asyncio, ruff, mypy. Makefile: `install, up, temporal, worker, payer, api, test, lint, eval-smoke, eval-full, demo`.
- [x] **T0.2 Agent files** · you — create `AGENTS.md` from Appendix A; `CLAUDE.md` containing the single line `@AGENTS.md`; `.claude/commands/task.md` from Appendix B; empty `PROGRESS.md`.
- [x] **T0.3 Config, compose, CI** · Claude Code · small — Postgres (pgvector) + Redis only in compose; CI with `OFFLINE=1`.
- [x] **T0.4 Discovery + threat model** · you + claude.ai — prior-auth workflow today, roles, pain (minutes per case, denial causes), success metrics; threats: PHI leakage, cross-clinic access, fabricated clinical claims, injected text in clinical notes, duplicate submissions.
- [x] **T0.5 agentcore** · Claude Code — if you have agentcore from another project, copy `src/agentcore/` and its tests, rename package refs, run tests. Otherwise build: llm.py (LiteLLM, structured outputs, cost), routing.py (fallback, budgets), offline.py, telemetry.py (OTel GenAI attrs), guardrails.py (`@guarded`), audit.py (hash chain), auth.py (Clerk JWT + RBAC), cache.py (scoped keys), memory.py.
  - Done when: agentcore tests pass with OFFLINE=1.

## Phase 1 — Data

- [x] **T1.1 Synthetic patients** · Claude Code · default — download Synthea sample FHIR R4 bundles (or generate a small population once); `fhir/loader.py` loads Patient, Condition, Observation, Procedure, MedicationRequest, DiagnosticReport, DocumentReference into `fhir_resources(id, type, patient_id, clinic_id, effective_at, resource jsonb)`.
  - Done when: ≥200 patients loaded across 2 clinics; test fetches a patient's conditions.
- [x] **T1.2 Real coverage policies** · you + Claude Code — pick 6 procedures (e.g. lumbar spine MRI, knee MRI, sleep study, CT abdomen, outpatient PT extension, a specialty drug). Download public Medicare coverage determinations and 2 commercial insurers' public medical policies for them into `data/policies/raw/` with source URL and effective date. `policies/ingest.py` parses into `policies(payer, procedure, version, effective_from, effective_to, text, source_url)`.
- [x] **T1.3 Criteria checklists** · Claude Code · strong — `policies/checklist.py` decomposes each policy version into `Criterion(id, text, kind: rule|judgment, rule_spec?)`; you review and correct every checklist by hand (they become ground truth).
- [x] **T1.4 Rules engine** · Claude Code · small — `policies/rules.py` evaluates `rule` criteria in Python (age, diagnosis code sets, prior imaging within N months, conservative therapy duration from Procedure/MedicationRequest dates).
  - Done when: unit tests per rule type.

## Phase 2 — Retrieval

- [ ] **T2.1 Policy RAG** · Claude Code · default — chunk by criterion; embed locally (bge-small); hybrid BM25 + pgvector + RRF + cross-encoder rerank; filters payer + procedure + effective date INSIDE the query.
- [ ] **T2.2 Chart retrieval + evidence cards** · Claude Code · default — `fhir/evidence_cards.py`: per criterion, structured FHIR query by resource type and date window + semantic search over DocumentReference note text; output `EvidenceCard(criterion_id, summary, fhir_refs[])`; cache cards per (patient, encounter, criterion).
- [ ] **T2.3 Stage traces + retrieval eval** · Claude Code · small — spans per stage; label 60 criterion→evidence pairs; Recall/precision report in `docs/results/retrieval.md`.

## Phase 3 — Payer service

- [x] **T3.1 Payer API** · Claude Code · default — separate FastAPI app modelled on FHIR-based prior-auth exchange: `POST /claims/prior-auth` (returns pended/approved/denied/more-info deterministically from hidden case labels), `GET /status/{id}`, webhook callbacks to our API, denial reason codes.
- [x] **T3.2 Failure modes** · Claude Code · small — configurable latency, 429 with Retry-After, 500s, outage windows, duplicate webhooks, out-of-order webhooks.

## Phase 4 — MCP servers

- [x] **T4.1 Base** · Claude Code · strong — FastMCP wrapper: JWT verify, clinic scoping, RBAC per tool, audit event, span, timeout, circuit breaker, `risk` label.
- [x] **T4.2 fhir_read** · Claude Code · small — `get_patient_summary`, `query_resources(type, since, codes)`, `search_notes(query)`; minimum-necessary fields only.
- [x] **T4.3 policy_search** · Claude Code · small — `get_policy(payer, procedure, as_of)`, `search_policy(query, payer, procedure, as_of)`.
- [x] **T4.4 payer** · Claude Code · default — `submit_prior_auth(packet, approval_token)` (write, idempotency key = hash(case_id, attempt)), `get_status(id)`.
- [x] **T4.5 documents** · Claude Code · small — render letter of medical necessity / appeal to PDF from structured draft.

## Phase 5 — Agents (LangGraph sub-graphs)

- [x] **T5.1 State + schemas** · Claude Code · strong — case state, `CriterionDecision(criterion_id, status met|not_met|unknown, evidence_refs, confidence, method rule|agent)`, reducers for parallel writes.
- [x] **T5.2 Intake** · Claude Code · small — normalize codes, payer, plan; select policy version.
- [x] **T5.3 Evidence + Policy agents (parallel)** · Claude Code · default — evidence agent builds cards; policy agent returns checklist for the version.
- [x] **T5.4 Criteria decision** · Claude Code · default — rules first (T1.4), agent only for judgment criteria; confidence per criterion.
- [x] **T5.5 Submission agent** · Claude Code · default — packet + letter; every clinical sentence carries `[fhir:<id>]` refs.
- [x] **T5.6 Verifier** · Claude Code · default — citation gate (refs exist and support the sentence), criteria consistency; `pass|revise|escalate`.
- [x] **T5.7 Appeals agent** · Claude Code · default — map denial reason code → missing/misread criteria → evidence → appeal draft.
- [x] **T5.8 Supervisor + sub-graphs** · Claude Code · strong — `agents/graphs.py`: `assess_graph` (intake → evidence ∥ policy → criteria), `draft_graph` (submission → verifier → revise ≤2), `appeal_graph`; all nodes `@guarded`.
  - Done when: offline run of each sub-graph on 3 sample cases.

## Phase 6 — Durable workflow (Temporal)

- [x] **T6.1 Activities** · Claude Code · default — wrap each sub-graph and each MCP write as an activity with timeouts and retry policies (LLM: 3 attempts, backoff; payer submit: non-retryable on 4xx, idempotent on retry).
- [x] **T6.2 Workflow** · Claude Code · strong — `PriorAuthCase` workflow: stages per §1; signals `clinician_answer`, `coordinator_decision`, `payer_update`; queries `current_state`; reminder timers (e.g. 24h clinician nudge); payer outage → park on timer; Continue-As-New after appeal cycles.
- [x] **T6.3 Worker + versioning** · Claude Code · small — worker entrypoint; demonstrate a `workflow.patched()` change with a running case.
  - Done when: start a case, kill the worker mid-stage, restart, case completes; Temporal UI screenshot saved.

## Phase 7 — API, HITL, UI

- [x] **T7.1 API** · Claude Code · default — create case, list cases, case detail, SSE stage events, endpoints that send Temporal signals, payer webhook receiver (dedupe by event id).
- [x] **T7.2 HITL policies** · Claude Code · small — approval required for every submission; manager queue for low confidence, high cost, second denial; overrides saved as eval data.
- [x] **T7.3 Next.js** · Claude Code · default — Clerk auth; role views: coordinator queue, case timeline, evidence-vs-criteria table with FHIR citations, approve/edit/reject; clinician inbox; manager queue.
- [x] **T7.4 Episodic memory** · Claude Code · default — on payer outcome signal, write `(payer, procedure, outcome, denial_reason)`; nightly consolidation → per-payer playbook notes, expiring on policy version change; retrieved by supervisor before submission.

## Phase 8 — Security hardening

- [x] **T8.1 RLS + RBAC** · Claude Code — clinic RLS on all tables; roles coordinator, clinician, manager, auditor; tests for cross-clinic denial.
- [x] **T8.2 PHI redaction** · Claude Code · small — span/log processor masking names, DOB, MRN, addresses; test that traces contain no PHI fields.
- [x] **T8.3 Injection in notes** · Claude Code · small — clinical note text treated as untrusted; screening + tests with injected notes.

## Phase 9 — Evaluation

- [x] **T9.1 Case suite** · Claude Code · default + you — `evals/cases/*.yaml`: patient id, order, payer, hidden facts for clinician, expected end state, expected per-criterion labels. Start 50 (1 payer × 3 procedures), grow to 200.
- [x] **T9.2 Baseline + runner** · Claude Code — single-agent baseline with the same tools; runner executes workflows in a test Temporal environment with the simulated clinician (`clinician_sim.py`, answers only from hidden facts) and payer service; pass^1 and pass^k (k=3 default on free tier).
- [x] **T9.3 Accuracy + citation judge** · Claude Code · small — criteria accuracy; citation precision judge calibrated on 50 hand-checked letters (`docs/results/judge_calibration.md`); unsupported-claim rate.
- [x] **T9.4 Fault injection** · Claude Code — kill workers, mid-case deploy (patched), payer 500/429/outage, duplicate and out-of-order webhooks; assert exactly-once submission and correct end states over 120 injected faults.
- [x] **T9.5 Report + CI gate** · Claude Code · small — `docs/results/summary.md` vs baseline; CI runs 30-case offline subset with thresholds.

## Phase 10 — Cost and performance

- [x] **T10.1 Routing** · Claude Code — small model for intake/evidence extraction, strong for criteria judgment and appeals; measure cost per case before/after.
- [x] **T10.2 Context compression** · Claude Code · small — evidence cards replace raw notes in prompts; token reduction measured.
- [x] **T10.3 Prompt caching** · Claude Code · small — policy text and system prompts as stable prefixes.

## Phase 11 — Deploy and polish

- [ ] **T11.1 Containers + deploy** · Claude Code · small — Dockerfiles (api, worker, payer); deploy free tiers; Temporal: keep dev server for demos or a single small VM; Terraform for AWS kept honest (apply only via free credits/LocalStack).
- [ ] **T11.2 README, diagrams, demo** · you — Appendix C.

---

## Appendix A — AGENTS.md

```markdown
# Clearance — agent instructions
Durable prior-authorization platform. Full plan: plan.md (read §0 and only your task).
Commands: make install | up | temporal | worker | payer | api | test | lint | eval-smoke | demo
Layout: src/agentcore, src/clearance/{fhir,policies,retrieval,mcp_servers,agents,workflows,hitl,api}, payer_service/, evals/, apps/web
Rules:
- Temporal workflow code is deterministic; all I/O in activities.
- All LLM calls via agentcore/llm.py; tools via MCP; nodes wrapped by @guarded; Pydantic outputs.
- Rule-checkable criteria in Python, never a model. Every clinical claim cites a FHIR id.
- Synthetic data only; redact PHI in logs/traces. OFFLINE=1 keeps tests passing.
- Do not read: data/**, evals/cases/**, tests/fixtures/**, apps/web/node_modules/**
- Finish = tests pass → tick task in plan.md → one line in PROGRESS.md → commit "<type>(Tx.y): summary".
```

## Appendix B — .claude/commands/task.md (custom slash command)

```markdown
Do task $ARGUMENTS in plan.md.
Read AGENTS.md rules, plan.md §0, and ONLY task $ARGUMENTS plus the files it names.
First give a plan in at most 5 bullets and wait for my OK.
Then implement until the task's "Done when" passes (run the tests).
Finish: tick the task checkbox in plan.md, append one line to PROGRESS.md, commit "<type>($ARGUMENTS): summary".
```

Usage in Claude Code: `/task T3.2`

## Appendix C — README structure

Pitch + GIF · Problem · Results vs baseline (pass^k, criteria accuracy, unsupported claims, exactly-once, touch time, cost) · Architecture (Temporal outside, LangGraph inside) · Production spine checklist · Evaluation method (real policies, simulated clinician, labels) · Security/PHI controls · Quickstart · Decisions and trade-offs · Roadmap.
