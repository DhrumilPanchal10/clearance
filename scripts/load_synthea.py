"""Operational one-time loader for Synthea FHIR bundles.

Not part of the test suite. Example:

    uv run python -m scripts.load_synthea --src data/synthea/fhir --limit 300

Defaults to a local SQLite file so it runs with no Postgres; pass --db to target
Postgres (pgvector) started via ``make up``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import func, select

from clearance.db import make_engine, make_session_factory
from clearance.fhir.loader import load_bundle
from clearance.models import Base, FhirResource


async def _run(src: Path, db_url: str, limit: int | None) -> None:
    engine = make_engine(db_url)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = make_session_factory(engine)

    files = sorted(src.glob("*.json"))
    if limit is not None:
        # Prefer patient bundles over hospital/practitioner info files.
        files = [f for f in files if "Information" not in f.name][:limit]

    loaded = 0
    async with factory() as session:
        for file in files:
            bundle = json.loads(file.read_text())
            await load_bundle(session, bundle)
            loaded += 1
        await session.commit()

        patients = await session.scalar(
            select(func.count()).select_from(FhirResource).where(FhirResource.type == "Patient")
        )
        clinics = (
            await session.execute(
                select(FhirResource.clinic_id, func.count())
                .where(FhirResource.type == "Patient")
                .group_by(FhirResource.clinic_id)
            )
        ).all()
        total = await session.scalar(select(func.count()).select_from(FhirResource))

    await engine.dispose()
    print(f"bundles loaded : {loaded}")
    print(f"patients       : {patients}")
    print(f"total resources: {total}")
    print(f"clinics        : {dict(clinics)}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Load Synthea FHIR bundles into the DB.")
    ap.add_argument("--src", type=Path, required=True, help="Directory of *.json bundles")
    ap.add_argument(
        "--db",
        default="sqlite+aiosqlite:///data/synthea.db",
        help="Async SQLAlchemy URL (default: local SQLite file)",
    )
    ap.add_argument("--limit", type=int, default=None, help="Max patient bundles to load")
    args = ap.parse_args()
    asyncio.run(_run(args.src, args.db, args.limit))


if __name__ == "__main__":
    main()
