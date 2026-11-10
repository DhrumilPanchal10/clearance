"""Select the policy version in force on a given date (plan T1.2).

The version whose ``[effective_from, effective_to)`` interval contains ``as_of``
is authoritative; ``effective_to is None`` means currently in force. Effective
date is part of the retrieval query, never applied after the fact.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clearance.models import Policy


def select_in_force(policies: list[Policy], as_of: date) -> Policy | None:
    """From candidate versions, return the one in force on ``as_of``."""
    in_force = [
        p
        for p in policies
        if p.effective_from <= as_of and (p.effective_to is None or as_of < p.effective_to)
    ]
    if not in_force:
        return None
    return max(in_force, key=lambda p: p.effective_from)


async def get_policy(
    session: AsyncSession, payer: str, procedure: str, as_of: date
) -> Policy | None:
    """Fetch the (payer, procedure) policy version in force on ``as_of``."""
    rows = list(
        await session.scalars(
            select(Policy).where(Policy.payer == payer, Policy.procedure == procedure)
        )
    )
    return select_in_force(rows, as_of)
