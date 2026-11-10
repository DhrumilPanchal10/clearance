"""Temporal worker entrypoint (plan T6.3).

Wires production dependencies, registers the PriorAuthCase workflow and the
activities, and polls the task queue. Requires a Temporal server
(``temporal server start-dev``); run with ``make worker``.
"""

from __future__ import annotations

import asyncio

import httpx
from temporalio.client import Client
from temporalio.worker import Worker

from agentcore.audit import AuditLog
from clearance.agents.supervisor import make_checklist_loader, make_policy_version_lookup
from clearance.config import settings
from clearance.db import make_engine, make_session_factory
from clearance.workflows.activities import ALL_ACTIVITIES as ACTIVITIES
from clearance.workflows.activities import ActivityDeps, set_activity_deps
from clearance.workflows.prior_auth import PriorAuthCase


def build_default_deps() -> ActivityDeps:
    session_factory = make_session_factory(make_engine())
    return ActivityDeps(
        session_factory=session_factory,
        audit_log=AuditLog(),
        payer_client=httpx.AsyncClient(base_url=settings.payer_base_url, timeout=30),
        get_version=make_policy_version_lookup(session_factory),
        load_checklist=make_checklist_loader(),
    )


async def main() -> None:
    set_activity_deps(build_default_deps())
    client = await Client.connect(settings.temporal_host, namespace=settings.temporal_namespace)
    worker = Worker(
        client,
        task_queue=settings.temporal_task_queue,
        workflows=[PriorAuthCase],
        activities=ACTIVITIES,
    )
    await worker.run()


if __name__ == "__main__":
    asyncio.run(main())
