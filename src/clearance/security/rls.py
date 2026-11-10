"""Row-level clinic isolation (plan T8.1).

Two layers of defense keep one clinic from ever reading another's data:

1. **Postgres RLS** (authoritative). Every tenant-scoped table enables row
   security with a policy keyed on the ``app.clinic_id`` GUC. The application
   sets that GUC per transaction via :func:`set_clinic`, so even a bug in a
   query cannot cross clinics — the database filters rows itself. The DDL is in
   :data:`RLS_STATEMENTS` and is applied by ``scripts/apply_rls.py`` /
   migrations against Postgres.

2. **Application guard** (works everywhere, incl. the SQLite test DB where RLS
   is unavailable). Tool calls run under a :class:`ToolContext` whose
   ``clinic_id`` is enforced by the MCP base guard, and :func:`assert_clinic`
   is the explicit check used at trust boundaries.

Roles: coordinator, clinician, manager, auditor — their table/permission matrix
lives in :mod:`clearance.mcp_servers.base` (per-tool RBAC).
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Tables carrying a clinic_id that must be clinic-isolated.
TENANT_TABLES = ("fhir_resources",)

GUC = "app.clinic_id"


class ClinicIsolationError(PermissionError):
    """Raised when an actor touches a row outside its clinic."""


def _policy_sql(table: str) -> list[str]:
    return [
        f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;",
        f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;",
        f"DROP POLICY IF EXISTS {table}_clinic_isolation ON {table};",
        # Rows are visible/writable only when their clinic matches the GUC.
        f"CREATE POLICY {table}_clinic_isolation ON {table} "
        f"USING (clinic_id = current_setting('{GUC}', true)) "
        f"WITH CHECK (clinic_id = current_setting('{GUC}', true));",
    ]


RLS_STATEMENTS: list[str] = [stmt for table in TENANT_TABLES for stmt in _policy_sql(table)]


async def set_clinic(session: AsyncSession, clinic_id: str) -> None:
    """Scope the current transaction to one clinic (Postgres RLS GUC).

    No-op semantics on SQLite (the ``SET LOCAL`` simply has no effect there),
    so tests keep working while production gets real row-level enforcement.
    """
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    await session.execute(text(f"SET LOCAL {GUC} = :cid"), {"cid": clinic_id})


async def apply_rls(session: AsyncSession) -> None:
    """Apply the RLS DDL (idempotent). Postgres only."""
    bind = session.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for stmt in RLS_STATEMENTS:
        await session.execute(text(stmt))


def assert_clinic(actor_clinic: str, row_clinic: str) -> None:
    """Trust-boundary check used by code paths that join across clinic ids."""
    if actor_clinic != row_clinic:
        raise ClinicIsolationError(
            f"actor clinic {actor_clinic!r} may not access clinic {row_clinic!r}"
        )
