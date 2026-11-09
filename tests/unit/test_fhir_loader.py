"""Tests for clearance/fhir/loader.py (T1.1)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from clearance.fhir.loader import (
    assign_clinic,
    get_conditions,
    load_bundle,
    rows_from_bundle,
)
from clearance.models import FhirResource

PATIENT_ID = "pat-0001"


def _bundle() -> dict[str, Any]:
    return {
        "resourceType": "Bundle",
        "type": "transaction",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": PATIENT_ID,
                    "name": [{"family": "Doe"}],
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-late",
                    "subject": {"reference": f"urn:uuid:{PATIENT_ID}"},
                    "onsetDateTime": "2022-06-01T00:00:00Z",
                    "code": {
                        "coding": [{"code": "M54.5", "system": "http://hl7.org/fhir/sid/icd-10"}]
                    },
                }
            },
            {
                "resource": {
                    "resourceType": "Condition",
                    "id": "cond-early",
                    "subject": {"reference": f"Patient/{PATIENT_ID}"},
                    "onsetDateTime": "2020-01-01T00:00:00Z",
                    "code": {"coding": [{"code": "M51.26"}]},
                }
            },
            {
                "resource": {
                    "resourceType": "Procedure",
                    "id": "proc-1",
                    "subject": {"reference": f"urn:uuid:{PATIENT_ID}"},
                    "performedPeriod": {"start": "2021-03-02T10:00:00Z"},
                }
            },
            # An unwanted type that must be skipped.
            {"resource": {"resourceType": "Encounter", "id": "enc-1"}},
        ],
    }


def test_rows_from_bundle_extracts_wanted_types_only() -> None:
    rows = rows_from_bundle(_bundle())
    types = sorted(r.type for r in rows)
    assert types == ["Condition", "Condition", "Patient", "Procedure"]


def test_patient_id_and_reference_normalization() -> None:
    rows = {r.id: r for r in rows_from_bundle(_bundle())}
    # Patient points at itself.
    assert rows[PATIENT_ID].patient_id == PATIENT_ID
    # Both urn:uuid: and Patient/ references normalize to the bare id.
    assert rows["cond-late"].patient_id == PATIENT_ID
    assert rows["cond-early"].patient_id == PATIENT_ID
    assert rows["proc-1"].patient_id == PATIENT_ID


def test_effective_at_parsing_including_period() -> None:
    rows = {r.id: r for r in rows_from_bundle(_bundle())}
    assert rows["cond-early"].effective_at is not None
    assert rows["cond-early"].effective_at.year == 2020
    # performedPeriod.start is used for Procedure.
    assert rows["proc-1"].effective_at is not None
    assert rows["proc-1"].effective_at.year == 2021
    # Patient has no clinical timestamp.
    assert rows[PATIENT_ID].effective_at is None


def test_clinic_assignment_is_deterministic_and_binary() -> None:
    first = assign_clinic(PATIENT_ID)
    assert first == assign_clinic(PATIENT_ID)
    assert first in {"clinic-a", "clinic-b"}
    both = {assign_clinic(f"pat-{i:04d}") for i in range(50)}
    assert both == {"clinic-a", "clinic-b"}


async def test_load_bundle_and_get_conditions(session: AsyncSession) -> None:
    written = await load_bundle(session, _bundle())
    assert written == 4

    total = await session.scalar(select(func.count()).select_from(FhirResource))
    assert total == 4

    conditions = await get_conditions(session, PATIENT_ID)
    assert [c.id for c in conditions] == ["cond-early", "cond-late"]  # ordered by onset


async def test_load_bundle_is_idempotent(session: AsyncSession) -> None:
    await load_bundle(session, _bundle())
    await load_bundle(session, _bundle())
    total = await session.scalar(select(func.count()).select_from(FhirResource))
    assert total == 4  # merge, not duplicate
