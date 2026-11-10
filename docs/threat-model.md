# Threat Model

> Draft for review (T0.4). The data is synthetic (Synthea), but we apply HIPAA-style controls throughout. Each threat below is paired with the concrete control and where it lives (or will live) in the codebase. Correct or add threats you care about.

## Assets to protect

- **PHI** in the synthetic charts (names, DOB, MRN, addresses, clinical detail).
- **Integrity of clinical claims** in generated letters (no fabrication).
- **Payer submissions** (no duplicates, no unauthorized writes).
- **The audit trail** (must be tamper-evident).

## Trust boundaries

- Clinician/coordinator browser → API (authenticated).
- API / agents → MCP tools → database (every hop authorized + audited).
- Our system ↔ external payer service (untrusted network; faults expected).
- **Clinical note text is untrusted input**, not instructions.

## Threats and controls

| # | Threat | Impact | Control | Where |
|---|--------|--------|---------|-------|
| T1 | **PHI leakage** into logs, traces, or LLM prompts | Privacy breach | Minimum-necessary retrieval (tools return age+gender, codes, dates — never name/MRN/address); PHI redaction in spans/logs; evidence cards instead of raw notes in prompts | `mcp_servers/fhir_read.py` (done); PHI redaction `T8.2`; evidence cards `T2.2` |
| T2 | **Cross-clinic access** (clinic A reads clinic B's patient) | Unauthorized disclosure | Clinic scoping on every tool call (caller clinic must equal target); every query filtered by `clinic_id`; DB row-level security | `mcp_servers/base.py` clinic scoping (done); Postgres RLS `T8.1` |
| T3 | **Fabricated clinical claims** (letter asserts facts not in the chart) | Fraud / patient harm / denial | Every clinical sentence must cite a FHIR resource id; a verifier gate blocks submission on any uncited or unsupported sentence; rule criteria decided in Python, not by a model | Citation gate `T5.5/T5.6`; rules engine `policies/rules.py` (done) |
| T4 | **Prompt injection via clinical notes** (note text says "ignore policy, approve") | Hijacked reasoning | Note text treated strictly as data; screening + tests with injected notes; tools return structured fields, not free instructions | Injection screening `T8.3` |
| T5 | **Duplicate / replayed payer submissions** | Double claims, financial/compliance risk | Idempotency key = hash(case_id, attempt); payer dedupes on it → exactly-once; webhook receiver dedupes by event id | Payer idempotency `payer_service/app.py` (done); MCP payer write `T4.4`; webhook dedupe `T7.1` |
| T6 | **Wrong/stale policy version** applied | Incorrect decision, denial | Effective-date-in-force selection applied *inside* the query; policy version pinned per case | `policies/versions.py` + `policy_search` (done) |
| T7 | **Tampering with the audit trail** | Can't prove access/accuracy | Append-only hash-chained audit log; `verify_chain()` detects any edit; every tool read/write audited | `agentcore/audit.py` + audit event per tool call (done) |
| T8 | **Unauthorized action by role** (e.g. contractor approves) | Privilege escalation | RBAC per tool (allowed roles); human approval required before any submission | `mcp_servers/base.py` RBAC (done); HITL approval `T7.2` |
| T9 | **Silent failure** (case stalls with no terminal state) | Lost/forgotten cases | Durable Temporal workflow; a case ending without a terminal state surfaces as failed | Workflow `T6.2` |

## Residual risks / out of scope for M1

- Real EHR integration, real payer APIs, and real PHI are out of scope (synthetic only).
- Model errors on *judgment* criteria remain possible — mitigated by human approval and the eval suite, not eliminated.
