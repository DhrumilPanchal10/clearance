"""Parse raw coverage-policy files into the ``policies`` table (plan T1.2).

Each raw policy is a Markdown file with a simple ``---`` front-matter block::

    ---
    payer: medicare
    procedure: lumbar_spine_mri
    version: 2023
    effective_from: 2023-01-01
    effective_to:
    source_url: https://www.cms.gov/medicare-coverage-database/...
    ---
    <full policy text>

Only synthetic/public policy text is stored. No model interprets the text here;
decomposition into criteria is T1.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clearance.models import Policy

_REQUIRED = ("payer", "procedure", "version", "effective_from", "source_url")


@dataclass(slots=True)
class PolicyDoc:
    payer: str
    procedure: str
    version: str
    effective_from: date
    effective_to: date | None
    source_url: str
    text: str


class PolicyParseError(ValueError):
    """Raised when a raw policy file is malformed."""


def _parse_front_matter(raw: str, *, source: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        raise PolicyParseError(f"{source}: missing front-matter fence")
    parts = raw.split("---", 2)
    if len(parts) < 3:
        raise PolicyParseError(f"{source}: unterminated front-matter")
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if not line.strip() or ":" not in line:
            continue
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].strip()


def parse_policy_text(raw: str, *, source: str = "<string>") -> PolicyDoc:
    meta, body = _parse_front_matter(raw, source=source)
    missing = [k for k in _REQUIRED if not meta.get(k)]
    if missing:
        raise PolicyParseError(f"{source}: missing front-matter keys: {missing}")
    if not body:
        raise PolicyParseError(f"{source}: empty policy body")
    eff_to = meta.get("effective_to") or ""
    return PolicyDoc(
        payer=meta["payer"],
        procedure=meta["procedure"],
        version=meta["version"],
        effective_from=date.fromisoformat(meta["effective_from"]),
        effective_to=date.fromisoformat(eff_to) if eff_to else None,
        source_url=meta["source_url"],
        text=body,
    )


def parse_policy_file(path: str | Path) -> PolicyDoc:
    p = Path(path)
    return parse_policy_text(p.read_text(), source=p.name)


async def upsert_policy(session: AsyncSession, doc: PolicyDoc) -> Policy:
    """Insert or update the policy identified by (payer, procedure, version)."""
    existing = await session.scalar(
        select(Policy).where(
            Policy.payer == doc.payer,
            Policy.procedure == doc.procedure,
            Policy.version == doc.version,
        )
    )
    row = existing or Policy(payer=doc.payer, procedure=doc.procedure, version=doc.version)
    row.effective_from = doc.effective_from
    row.effective_to = doc.effective_to
    row.text = doc.text
    row.source_url = doc.source_url
    session.add(row)
    await session.flush()
    return row


async def ingest_directory(session: AsyncSession, path: str | Path) -> int:
    """Parse and upsert every ``*.md`` policy under ``path``. Returns count."""
    count = 0
    for file in sorted(Path(path).glob("*.md")):
        await upsert_policy(session, parse_policy_file(file))
        count += 1
    await session.commit()
    return count
