"""fhir_read MCP server (plan T4.2).

Tools: get_patient_summary, query_resources, search_notes. Every query is scoped
to the caller's clinic and returns the minimum-necessary fields — never raw PHI
such as name, address, SSN or MRN.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agentcore.audit import AuditLog
from clearance.mcp_servers.base import Risk, ToolContext, mcp_tool
from clearance.models import FhirResource
from clearance.security.injection import screen_note

# Clinical reads: clinic staff only (auditor reviews the audit log, not PHI).
_READ_ROLES = frozenset({"coordinator", "clinician", "manager"})


def _codes_of(resource: dict[str, Any], *keys: str) -> list[str]:
    out: list[str] = []
    for key in keys or ("code",):
        concept = resource.get(key)
        if isinstance(concept, dict):
            for coding in concept.get("coding", []) or []:
                if isinstance(coding.get("code"), str):
                    out.append(coding["code"])
    return out


def _age(birth: str | None, as_of: date) -> int | None:
    if not birth:
        return None
    try:
        b = date.fromisoformat(birth)
    except ValueError:
        return None
    return as_of.year - b.year - ((as_of.month, as_of.day) < (b.month, b.day))


def build_fhir_read_tools(
    session_factory: async_sessionmaker[AsyncSession], audit_log: AuditLog
) -> SimpleNamespace:
    async def _scoped(
        session: AsyncSession, clinic_id: str, patient_id: str, rtype: str | None
    ) -> list[FhirResource]:
        stmt = select(FhirResource).where(
            FhirResource.clinic_id == clinic_id,
            FhirResource.patient_id == patient_id,
        )
        if rtype is not None:
            stmt = stmt.where(FhirResource.type == rtype)
        return list(await session.scalars(stmt))

    @mcp_tool("get_patient_summary", allowed_roles=_READ_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def get_patient_summary(ctx: ToolContext, *, patient_id: str) -> dict[str, Any]:
        async with session_factory() as s:
            rows = await _scoped(s, ctx.clinic_id, patient_id, None)
        patient = next((r for r in rows if r.type == "Patient"), None)
        conditions = [
            {"id": r.id, "codes": _codes_of(r.resource), "onset": _iso(r.effective_at)}
            for r in rows
            if r.type == "Condition"
        ]
        # Minimum-necessary demographics only: age + gender, never name/address/MRN.
        demographics: dict[str, Any] = {}
        if patient is not None:
            demographics = {
                "age": _age(patient.resource.get("birthDate"), date.today()),
                "gender": patient.resource.get("gender"),
            }
        return {
            "patient_id": patient_id,
            "demographics": demographics,
            "conditions": conditions,
            "counts": {
                t: sum(1 for r in rows if r.type == t)
                for t in ("Procedure", "MedicationRequest", "Observation", "DocumentReference")
            },
        }

    @mcp_tool("query_resources", allowed_roles=_READ_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def query_resources(
        ctx: ToolContext,
        *,
        patient_id: str,
        type: str,
        since: str | None = None,
        codes: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        async with session_factory() as s:
            rows = await _scoped(s, ctx.clinic_id, patient_id, type)
        since_dt = _parse(since) if since else None
        wanted = set(codes) if codes else None
        out: list[dict[str, Any]] = []
        for r in rows:
            if since_dt is not None and (r.effective_at is None or r.effective_at < since_dt):
                continue
            rcodes = _codes_of(r.resource, "code", "medicationCodeableConcept")
            if wanted is not None and not (wanted & set(rcodes)):
                continue
            out.append(
                {"id": r.id, "type": r.type, "effective_at": _iso(r.effective_at), "codes": rcodes}
            )
        return out

    @mcp_tool("search_notes", allowed_roles=_READ_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def search_notes(
        ctx: ToolContext, *, patient_id: str, query: str
    ) -> list[dict[str, Any]]:
        """Keyword search over DocumentReference notes (semantic search is T2.2)."""
        async with session_factory() as s:
            rows = await _scoped(s, ctx.clinic_id, patient_id, "DocumentReference")
        needle = query.lower()
        hits: list[dict[str, Any]] = []
        for r in rows:
            text = _note_text(r.resource)
            if needle in text.lower():
                # T8.3: note text is untrusted. Screen it; flag injection-suspect
                # notes so the evidence stage neutralizes them before any prompt.
                screen = screen_note(text)
                hits.append(
                    {
                        "id": r.id,
                        "date": _iso(r.effective_at),
                        "type": _codes_of(r.resource, "type"),
                        "untrusted": not screen.safe,
                        "screen_findings": screen.findings,
                    }
                )
        return hits

    @mcp_tool("get_patient_facts", allowed_roles=_READ_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def get_patient_facts(ctx: ToolContext, *, patient_id: str) -> dict[str, Any]:
        """Rule-ready facts for the rules engine: codes + dates only, no PHI."""
        async with session_factory() as s:
            rows = await _scoped(s, ctx.clinic_id, patient_id, None)
        patient = next((r for r in rows if r.type == "Patient"), None)

        def items(rtype: str, *keys: str) -> list[dict[str, Any]]:
            return [
                {"id": r.id, "codes": _codes_of(r.resource, *keys), "date": _iso(r.effective_at)}
                for r in rows
                if r.type == rtype
            ]

        return {
            "birth_date": patient.resource.get("birthDate") if patient else None,
            "conditions": items("Condition", "code"),
            "procedures": items("Procedure", "code"),
            "medications": items("MedicationRequest", "medicationCodeableConcept"),
        }

    return SimpleNamespace(
        get_patient_summary=get_patient_summary,
        query_resources=query_resources,
        search_notes=search_notes,
        get_patient_facts=get_patient_facts,
    )


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt is not None else None


def _parse(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _note_text(resource: dict[str, Any]) -> str:
    parts: list[str] = []
    if isinstance(resource.get("description"), str):
        parts.append(resource["description"])
    type_text = resource.get("type", {})
    if isinstance(type_text, dict) and isinstance(type_text.get("text"), str):
        parts.append(type_text["text"])
    for content in resource.get("content", []) or []:
        att = content.get("attachment", {}) if isinstance(content, dict) else {}
        if isinstance(att.get("title"), str):
            parts.append(att["title"])
    return " ".join(parts)
