"""Request/response schemas for the API (plan T7.1)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class CreateCaseRequest(BaseModel):
    patient_id: str
    payer: str
    procedure: str
    as_of: str  # ISO date
    case_id: str | None = None


class CoordinatorDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    note: str = ""


class ClinicianAnswerRequest(BaseModel):
    answers: dict[str, Any]


class PayerWebhookRequest(BaseModel):
    event_id: str
    case_id: str
    status: str
    denial_reason: str | None = None
