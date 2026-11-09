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
