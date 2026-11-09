# Clearance

Durable prior-authorization automation platform.

Clearance turns a prior-auth request into a durable, auditable case: it reads the patient chart (synthetic FHIR R4), pulls the payer's current coverage policy, decides each criterion (rules in Python, judgment by agents), drafts a letter of medical necessity where **every clinical claim cites a FHIR resource id**, routes it for human approval, submits to a simulated payer, and tracks the outcome — surviving worker restarts, payer outages, and appeals via a Temporal workflow.

> Status: early build. See [`plan.md`](plan.md) for the full implementation plan and [`PROGRESS.md`](PROGRESS.md) for what's done.

## Architecture

Temporal **outside** (one durable `PriorAuthCase` workflow per case), LangGraph **inside** each stage (agent sub-graphs). Tools are exposed only through MCP servers (auth + audit); all LLM calls go through `agentcore/llm.py`.

```
Next.js ──> FastAPI (JWT/RBAC) ──> Temporal workflow PriorAuthCase
   intake → [evidence ∥ policy] → criteria → draft → verify → submit → track → appeal
   each stage = Temporal activity running a LangGraph sub-graph
MCP servers: fhir_read · policy_search · payer · documents
Postgres (pgvector): fhir_resources(jsonb) · policies · cases · memory · audit (RLS per clinic)
Payer service: separate FastAPI app with injected failures
All hops → OpenTelemetry → Langfuse/Phoenix ; Temporal Web UI for history
```

## Quickstart

```bash
make install     # uv sync (deps + dev)
make up          # Postgres (pgvector) + Redis
make test        # OFFLINE=1 pytest — passes with no API keys
make lint        # ruff + mypy --strict
```

`OFFLINE=1` uses recorded LLM fixtures, so tests and CI run with no keys.

## Safety & data

Synthetic (Synthea) health data only. HIPAA-style controls regardless: minimum-necessary retrieval, PHI redaction in logs/traces, and an audit record of every read and write. Clinical note text is treated as untrusted input.
