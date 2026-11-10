"""Tests for policy ingest + version selection (T1.2)."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from clearance.models import Policy
from clearance.policies.ingest import (
    PolicyParseError,
    ingest_directory,
    parse_policy_text,
)
from clearance.policies.versions import get_policy, select_in_force

POLICY_2022 = """---
payer: medicare
procedure: lumbar_spine_mri
version: "2022"
effective_from: 2022-01-01
effective_to: 2023-01-01
source_url: https://www.cms.gov/x/2022
---
Lumbar spine MRI is covered when conservative therapy of at least 6 weeks has failed.
"""

POLICY_2023 = """---
payer: medicare
procedure: lumbar_spine_mri
version: "2023"
effective_from: 2023-01-01
effective_to:
source_url: https://www.cms.gov/x/2023
---
Lumbar spine MRI is covered when conservative therapy of at least 6 weeks has failed
and there is no repeat MRI within the prior 12 months.
"""


def test_parse_policy_text_fields_and_open_ended_version() -> None:
    doc = parse_policy_text(POLICY_2023)
    assert doc.payer == "medicare"
    assert doc.procedure == "lumbar_spine_mri"
    assert doc.effective_from == date(2023, 1, 1)
    assert doc.effective_to is None
    assert "no repeat MRI" in doc.text


def test_parse_rejects_missing_keys() -> None:
    with pytest.raises(PolicyParseError):
        parse_policy_text("---\npayer: medicare\n---\nbody")


def test_parse_rejects_empty_body() -> None:
    with pytest.raises(PolicyParseError):
        parse_policy_text(
            "---\npayer: p\nprocedure: x\nversion: 1\n"
            "effective_from: 2023-01-01\nsource_url: u\n---\n"
        )


def _policy(doc_text: str) -> Policy:
    d = parse_policy_text(doc_text)
    return Policy(
        payer=d.payer,
        procedure=d.procedure,
        version=d.version,
        effective_from=d.effective_from,
        effective_to=d.effective_to,
        text=d.text,
        source_url=d.source_url,
    )


def test_select_in_force_picks_correct_version() -> None:
    rows = [_policy(POLICY_2022), _policy(POLICY_2023)]

    before = select_in_force(rows, date(2022, 6, 1))
    assert before is not None and before.version == "2022"
    after = select_in_force(rows, date(2023, 6, 1))
    assert after is not None and after.version == "2023"
    # Boundary: effective_to is exclusive, so 2023-01-01 belongs to the 2023 version.
    boundary = select_in_force(rows, date(2023, 1, 1))
    assert boundary is not None and boundary.version == "2023"
    # Before any policy.
    assert select_in_force(rows, date(2020, 1, 1)) is None


async def test_ingest_directory_and_get_policy(session: AsyncSession, tmp_path: Path) -> None:
    (tmp_path / "lumbar_2022.md").write_text(POLICY_2022)
    (tmp_path / "lumbar_2023.md").write_text(POLICY_2023)

    count = await ingest_directory(session, tmp_path)
    assert count == 2

    older = await get_policy(session, "medicare", "lumbar_spine_mri", date(2022, 3, 1))
    assert older is not None and older.version == "2022"
    current = await get_policy(session, "medicare", "lumbar_spine_mri", date(2024, 1, 1))
    assert current is not None and current.version == "2023"


async def test_ingest_is_idempotent(session: AsyncSession, tmp_path: Path) -> None:
    (tmp_path / "lumbar_2023.md").write_text(POLICY_2023)
    await ingest_directory(session, tmp_path)
    await ingest_directory(session, tmp_path)
    current = await get_policy(session, "medicare", "lumbar_spine_mri", date(2024, 1, 1))
    assert current is not None and current.version == "2023"
