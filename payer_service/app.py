"""Payer service — a separate FastAPI app modelling a FHIR-based prior-auth
exchange (plan T3.1).

Outcomes are deterministic from hidden per-case labels (seeded by the eval
harness via the ``/_control`` endpoints) so the system under test is graded on
assembling the right packet, not on luck. Submission is idempotent on an
Idempotency-Key, giving exactly-once semantics under retries.
"""

from __future__ import annotations

import hashlib
from collections import deque
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fastapi import FastAPI, Header, Response
from pydantic import BaseModel, Field

from payer_service.failure_modes import FailureConfig


class Outcome(StrEnum):
    APPROVED = "approved"
    DENIED = "denied"
    PENDED = "pended"
    MORE_INFO = "more_info"


class DenialReason(StrEnum):
    CRITERIA_NOT_MET = "criteria_not_met"
    MISSING_DOCUMENTATION = "missing_documentation"
    NO_CONSERVATIVE_THERAPY = "no_conservative_therapy"
    NOT_MEDICALLY_NECESSARY = "not_medically_necessary"
    DUPLICATE = "duplicate"


# --------------------------------------------------------------------------- #
# Request / response schemas
# --------------------------------------------------------------------------- #


class PriorAuthRequest(BaseModel):
    case_id: str
    procedure: str
    packet: dict[str, Any] = Field(default_factory=dict)
    callback_url: str | None = None


class PriorAuthResponse(BaseModel):
    claim_id: str
    status: Outcome
    denial_reason: DenialReason | None = None
    reason_codes: list[str] = Field(default_factory=list)
    idempotent_replay: bool = False


class StatusResponse(BaseModel):
    claim_id: str
    case_id: str
    status: Outcome
    denial_reason: DenialReason | None = None


class PayerLabel(BaseModel):
    outcome: Outcome
    denial_reason: DenialReason | None = None


# --------------------------------------------------------------------------- #
# In-memory state (single-process demo/eval service)
# --------------------------------------------------------------------------- #


@dataclass
class _State:
    labels: dict[str, PayerLabel] = field(default_factory=dict)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    idempotency: dict[str, str] = field(default_factory=dict)
    failures: FailureConfig = field(default_factory=FailureConfig)
    seq: int = 0


state = _State()

_DEFAULT_DENIAL = DenialReason.CRITERIA_NOT_MET


def _default_outcome(case_id: str) -> PayerLabel:
    """Reproducible outcome for a case with no explicit label."""
    bucket = hashlib.sha256(case_id.encode()).digest()[0] % 10
    if bucket <= 5:
        return PayerLabel(outcome=Outcome.APPROVED)
    if bucket <= 7:
        return PayerLabel(outcome=Outcome.DENIED, denial_reason=_DEFAULT_DENIAL)
    if bucket == 8:
        return PayerLabel(outcome=Outcome.MORE_INFO)
    return PayerLabel(outcome=Outcome.PENDED)


def _resolve_label(case_id: str) -> PayerLabel:
    return state.labels.get(case_id) or _default_outcome(case_id)


def _new_claim_id() -> str:
    state.seq += 1
    return f"PA-{state.seq:06d}"


def _fault_response() -> Response | None:
    """Return an error Response if the current request should fault, else None."""
    status = state.failures.next_fault()
    if status is None:
        return None
    headers = {"Retry-After": str(state.failures.retry_after_s)} if status == 429 else {}
    body = {429: "rate_limited", 500: "internal_error", 503: "payer_outage"}.get(status, "error")
    return Response(
        content=f'{{"error":"{body}"}}',
        status_code=status,
        headers=headers,
        media_type="application/json",
    )


app = FastAPI(title="Clearance Payer Service")


@app.post("/claims/prior-auth")
async def submit_prior_auth(
    req: PriorAuthRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> Response:
    await state.failures.apply_latency()
    if (fault := _fault_response()) is not None:
        return fault

    # Exactly-once: a repeated idempotency key replays the first decision.
    if idempotency_key and idempotency_key in state.idempotency:
        claim_id = state.idempotency[idempotency_key]
        rec = state.claims[claim_id]
        return _json(
            PriorAuthResponse(
                claim_id=claim_id,
                status=rec["status"],
                denial_reason=rec["denial_reason"],
                reason_codes=rec["reason_codes"],
                idempotent_replay=True,
            )
        )

    label = _resolve_label(req.case_id)
    reason_codes = [label.denial_reason.value] if label.denial_reason else []
    claim_id = _new_claim_id()
    state.claims[claim_id] = {
        "case_id": req.case_id,
        "procedure": req.procedure,
        "status": label.outcome,
        "denial_reason": label.denial_reason,
        "reason_codes": reason_codes,
        "callback_url": req.callback_url,
    }
    if idempotency_key:
        state.idempotency[idempotency_key] = claim_id

    return _json(
        PriorAuthResponse(
            claim_id=claim_id,
            status=label.outcome,
            denial_reason=label.denial_reason,
            reason_codes=reason_codes,
        )
    )


@app.get("/status/{claim_id}")
async def get_status(claim_id: str) -> Response:
    await state.failures.apply_latency()
    if (fault := _fault_response()) is not None:
        return fault
    rec = state.claims.get(claim_id)
    if rec is None:
        return Response(
            content='{"error":"not_found"}', status_code=404, media_type="application/json"
        )
    return _json(
        StatusResponse(
            claim_id=claim_id,
            case_id=rec["case_id"],
            status=rec["status"],
            denial_reason=rec["denial_reason"],
        )
    )


# --------------------------------------------------------------------------- #
# Control plane (eval/test only — seeds hidden labels + failure config)
# --------------------------------------------------------------------------- #


@app.post("/_control/labels")
async def set_labels(labels: dict[str, PayerLabel]) -> dict[str, int]:
    state.labels.update(labels)
    return {"labels": len(state.labels)}


@app.post("/_control/failures")
async def set_failures(config: dict[str, Any]) -> dict[str, str]:
    inject = deque(config.get("inject_statuses", []))
    state.failures = FailureConfig(
        latency_ms=int(config.get("latency_ms", 0)),
        outage=bool(config.get("outage", False)),
        retry_after_s=int(config.get("retry_after_s", 2)),
        inject_statuses=inject,
        duplicate_webhooks=bool(config.get("duplicate_webhooks", False)),
        reorder_webhooks=bool(config.get("reorder_webhooks", False)),
    )
    return {"status": "ok"}


@app.post("/_control/reset")
async def reset() -> dict[str, str]:
    global state
    state = _State()
    return {"status": "reset"}


def _json(model: BaseModel) -> Response:
    return Response(content=model.model_dump_json(), media_type="application/json")
