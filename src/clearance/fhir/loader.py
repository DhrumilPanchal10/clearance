"""Load Synthea FHIR R4 bundles into ``fhir_resources``.

Only the resource types prior-auth reasoning needs are kept, and only synthetic
(Synthea) data is ever loaded.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from clearance.models import FhirResource

# Resource types we ingest (plan T1.1).
WANTED_TYPES: frozenset[str] = frozenset(
    {
        "Patient",
        "Condition",
        "Observation",
        "Procedure",
        "MedicationRequest",
        "DiagnosticReport",
        "DocumentReference",
    }
)

# Where each type carries its clinically-relevant timestamp, in priority order.
_DATE_FIELDS: dict[str, Sequence[str]] = {
    "Condition": ("onsetDateTime", "recordedDate"),
    "Observation": ("effectiveDateTime", "issued"),
    "Procedure": ("performedDateTime",),
    "MedicationRequest": ("authoredOn",),
    "DiagnosticReport": ("effectiveDateTime", "issued"),
    "DocumentReference": ("date",),
}

_CLINICS: tuple[str, ...] = ("clinic-a", "clinic-b")


def _normalize_ref(ref: str) -> str:
    """Strip ``urn:uuid:`` and ``ResourceType/`` prefixes from a FHIR reference."""
    if ref.startswith("urn:uuid:"):
        return ref[len("urn:uuid:") :]
    return ref.rsplit("/", 1)[-1]


def _subject_patient_id(resource: dict[str, Any]) -> str | None:
    for key in ("subject", "patient"):
        ref = resource.get(key, {})
        if isinstance(ref, dict) and isinstance(ref.get("reference"), str):
            return _normalize_ref(ref["reference"])
    return None


def _parse_dt(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _effective_at(resource: dict[str, Any]) -> datetime | None:
    rtype = resource.get("resourceType", "")
    for field in _DATE_FIELDS.get(rtype, ()):
        value = resource.get(field)
        if isinstance(value, str) and (dt := _parse_dt(value)) is not None:
            return dt
    # Period-shaped fields (e.g. Procedure.performedPeriod).
    for field in ("performedPeriod", "effectivePeriod"):
        period = resource.get(field)
        if isinstance(period, dict) and isinstance(period.get("start"), str):
            return _parse_dt(period["start"])
    return None


def assign_clinic(patient_id: str) -> str:
    """Deterministically map a patient to one of two clinics."""
    digest = hashlib.sha256(patient_id.encode()).digest()[0]
    return _CLINICS[digest % len(_CLINICS)]


def _iter_resources(bundle: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for entry in bundle.get("entry", []) or []:
        resource = entry.get("resource")
        if isinstance(resource, dict) and resource.get("resourceType") in WANTED_TYPES:
            yield resource


def rows_from_bundle(bundle: dict[str, Any], *, clinic_id: str | None = None) -> list[FhirResource]:
    """Convert a FHIR bundle into ``FhirResource`` rows (no DB access).

    If ``clinic_id`` is None the bundle's patient is assigned a clinic
    deterministically and every resource in the bundle inherits it.
    """
    resources = list(_iter_resources(bundle))
    patient_id = next(
        (r["id"] for r in resources if r.get("resourceType") == "Patient" and "id" in r),
        None,
    )
    clinic = clinic_id or (assign_clinic(patient_id) if patient_id else _CLINICS[0])

    rows: list[FhirResource] = []
    for resource in resources:
        rid = resource.get("id")
        if not isinstance(rid, str):
            continue
        rtype = resource["resourceType"]
        pid = rid if rtype == "Patient" else _subject_patient_id(resource)
        rows.append(
            FhirResource(
                id=rid,
                type=rtype,
                patient_id=pid,
                clinic_id=clinic,
                effective_at=_effective_at(resource),
                resource=resource,
            )
        )
    return rows


async def load_bundle(
    session: AsyncSession, bundle: dict[str, Any], *, clinic_id: str | None = None
) -> int:
    """Upsert one bundle's resources. Returns the number of rows written."""
    rows = rows_from_bundle(bundle, clinic_id=clinic_id)
    for row in rows:
        await session.merge(row)
    await session.flush()
    return len(rows)


async def load_directory(session: AsyncSession, path: str | Path) -> int:
    """Load every ``*.json`` bundle under ``path``. Returns total rows written."""
    total = 0
    for file in sorted(Path(path).glob("*.json")):
        bundle = json.loads(file.read_text())
        total += await load_bundle(session, bundle)
    await session.commit()
    return total


async def get_conditions(session: AsyncSession, patient_id: str) -> list[FhirResource]:
    """Fetch a patient's Condition resources (ordered by onset)."""
    stmt = (
        select(FhirResource)
        .where(FhirResource.patient_id == patient_id, FhirResource.type == "Condition")
        .order_by(FhirResource.effective_at)
    )
    return list((await session.scalars(stmt)).all())
