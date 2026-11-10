"""Production ASGI entrypoint: ``uvicorn clearance.api.main:app``.

Wires the real dependencies (FHIR database, payer write tool, LangGraph
sub-graphs, episodic memory). Requires Postgres + the payer service. For a
zero-infrastructure, fully clickable instance, use ``clearance.api.demo:app``.
"""

from __future__ import annotations

from clearance.api.app import create_app

app = create_app()
