"""Apply Postgres row-level clinic isolation (plan T8.1).

Run once against the Clearance database after tables exist:

    uv run python -m scripts.apply_rls

No-op on non-Postgres engines (the SQLite test DB enforces isolation at the
application layer instead). Idempotent — safe to re-run.
"""

from __future__ import annotations

import asyncio

from clearance.db import make_engine, make_session_factory
from clearance.security.rls import apply_rls


async def main() -> None:
    session_factory = make_session_factory(make_engine())
    async with session_factory() as session:
        await apply_rls(session)
        await session.commit()
    print("RLS policies applied (Postgres) or skipped (non-Postgres).")


if __name__ == "__main__":
    asyncio.run(main())
