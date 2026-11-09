# PROGRESS

One line per completed task: `Tx.y — summary (commit)`.

- T0.1 — Scaffolded repo layout, pyproject (temporal/langgraph/mcp/litellm/pgvector stack), Makefile.
- T0.2 — Agent files: AGENTS.md, CLAUDE.md (@AGENTS.md), .claude/commands/task.md, PROGRESS.md, plan.md.
- T0.3 — config.py, docker-compose (pgvector + Redis), .env.example, GitHub CI with OFFLINE=1.
- T0.5 — Copied agentcore spine from resolute; retargeted refs to `clearance`; 119 tests pass OFFLINE=1, ruff + mypy --strict clean.
