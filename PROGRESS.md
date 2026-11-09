# PROGRESS

One line per completed task: `Tx.y — summary (commit)`.

- T0.1 — Scaffolded repo layout, pyproject (temporal/langgraph/mcp/litellm/pgvector stack), Makefile.
- T0.2 — Agent files: AGENTS.md, CLAUDE.md (@AGENTS.md), .claude/commands/task.md, PROGRESS.md, plan.md.
- T0.3 — config.py, docker-compose (pgvector + Redis), .env.example, GitHub CI with OFFLINE=1.
- T0.5 — Copied agentcore spine from resolute; retargeted refs to `clearance`; 119 tests pass OFFLINE=1, ruff + mypy --strict clean.
- T1.1 — db.py/models.py (portable JSON/JSONB), fhir/loader.py (Synthea bundle → fhir_resources, clinic split, idempotent upsert), get_conditions; loaded 300 patients across 2 clinics (76k resources); 6 loader tests on in-memory SQLite.
