# Discovery — Prior Authorization Today

> Draft for review (T0.4). Describes the current-state workflow Clearance automates, who touches it, where the pain is, and how we'll measure success. Correct anything that doesn't match your mental model.

## What prior authorization is

Before certain procedures, imaging, or drugs are performed, the ordering clinician's office must get the health plan (payer) to agree, in advance, to cover them. The plan checks the request against its **coverage policy** — a document listing the clinical criteria that must be met (diagnosis, prior treatments tried, age, imaging history, etc.). If the request doesn't clearly show the criteria are met, it's **denied** or **pended for more information**.

## Who is involved (roles)

| Role | What they do today |
|------|--------------------|
| **Coordinator** (prior-auth / referral coordinator) | Owns the case end to end: reads the policy, digs through the chart for supporting evidence, assembles the request packet, submits to the payer, chases status, handles denials/appeals. This is the role drowning in manual work. |
| **Clinician** (ordering provider) | Places the order; answers the coordinator's clinical questions ("has the patient done 6 weeks of PT?"); signs the letter of medical necessity. Interrupted constantly for small facts. |
| **Manager** (practice/revenue manager) | Watches throughput and denial rates; steps in on high-cost, repeatedly-denied, or risky cases. |
| **Auditor / compliance** | After the fact, needs to prove who accessed which chart and why, and that submitted claims were accurate. |

## The workflow today (manual)

1. Order is placed → lands in the coordinator's queue.
2. Coordinator identifies the payer's **current** policy version for that procedure.
3. Coordinator reads the chart (conditions, prior imaging, medications, therapy notes) hunting for evidence for each criterion.
4. Gaps → coordinator messages the clinician and waits (often a day or more).
5. Coordinator writes a letter of medical necessity and submits the packet.
6. Payer responds: approved / denied / pended / needs-more-info — often after days.
7. Denial → coordinator interprets the reason code, finds the missing/misread evidence, and appeals.
8. Loop until a terminal outcome; outcome is logged for billing.

## Where the pain is

- **Touch time:** commonly **20–40+ minutes of human work per case**, spread across coordinator and clinician, much of it chart-hunting and re-keying.
- **Latency:** days of calendar time, dominated by waiting on clinician answers and payer responses.
- **Denials are expensive and often avoidable.** Leading causes:
  - *Missing/insufficient clinical documentation* (the evidence existed but wasn't surfaced or cited).
  - *Criteria not actually met yet* (e.g. conservative therapy duration too short) — submitted anyway.
  - *Wrong/stale policy version* applied.
  - *Transcription and coding errors.*
- **Volume + variability:** every payer has different criteria and they change over time.
- **Rework:** denied cases are re-worked from scratch; knowledge isn't reused across cases.

## How we'll measure success

| Metric | Why it matters |
|--------|----------------|
| **Criteria accuracy** vs hand-labeled ground truth | Are we deciding each criterion correctly? |
| **Unsupported-claim rate** (sentences in the letter with no valid FHIR citation) | Trust/safety: no fabricated clinical claims. |
| **First-pass approval / denial-overturn rate** | Did we assemble a winning packet? |
| **Exactly-once submission under faults** | No duplicate claims when things break. |
| **Human touch time per case** | The core productivity win. |
| **Cost per case** (LLM + infra) | Does it pencil out? |

## Scope for M1

One payer (**Medicare**) × three procedures (**lumbar spine MRI, knee MRI, CT abdomen/pelvis**), graded against a hand-labeled case suite, versus a single-agent baseline.
