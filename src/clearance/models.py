"""SQLAlchemy ORM models.

FHIR R4 resources are stored as JSON documents (JSONB on Postgres) and served by
our own read API — we do not run a FHIR server.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Portable JSON column: JSONB on Postgres, plain JSON elsewhere (e.g. SQLite in tests).
JsonDoc = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


class FhirResource(Base):
    """One FHIR R4 resource, keyed by its logical id.

    ``patient_id`` is the subject patient's id (a Patient row points at itself);
    ``clinic_id`` scopes the row for per-clinic row-level security.
    """

    __tablename__ = "fhir_resources"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    type: Mapped[str] = mapped_column(String, index=True)
    patient_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)
    clinic_id: Mapped[str] = mapped_column(String, index=True)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resource: Mapped[dict[str, Any]] = mapped_column(JsonDoc)
