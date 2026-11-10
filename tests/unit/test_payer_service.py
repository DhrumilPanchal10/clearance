"""Tests for the payer service (T3.1) and failure modes (T3.2)."""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from payer_service.app import app
from payer_service.failure_modes import FailureConfig, plan_webhook_deliveries


@pytest.fixture
def client() -> Iterator[TestClient]:
    c = TestClient(app)
    c.post("/_control/reset")
    yield c
    c.post("/_control/reset")


def _submit(client: TestClient, case_id: str, key: str | None = None) -> dict:
    headers = {"Idempotency-Key": key} if key else {}
    r = client.post(
        "/claims/prior-auth",
        json={"case_id": case_id, "procedure": "lumbar_spine_mri"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return r.json()


# --- deterministic outcomes ------------------------------------------------- #


def test_default_outcome_is_deterministic(client: TestClient) -> None:
    a = _submit(client, "case-xyz")
    client.post("/_control/reset")
    b = _submit(client, "case-xyz")
    assert a["status"] == b["status"]  # same hidden label → same outcome


def test_label_override_denied_with_reason(client: TestClient) -> None:
    client.post(
        "/_control/labels",
        json={"case-1": {"outcome": "denied", "denial_reason": "no_conservative_therapy"}},
    )
    res = _submit(client, "case-1")
    assert res["status"] == "denied"
    assert res["denial_reason"] == "no_conservative_therapy"
    assert res["reason_codes"] == ["no_conservative_therapy"]


def test_label_override_approved(client: TestClient) -> None:
    client.post("/_control/labels", json={"case-2": {"outcome": "approved"}})
    res = _submit(client, "case-2")
    assert res["status"] == "approved"
    assert res["denial_reason"] is None


# --- idempotency / exactly-once --------------------------------------------- #


def test_idempotent_submission_replays(client: TestClient) -> None:
    client.post("/_control/labels", json={"case-3": {"outcome": "approved"}})
    first = _submit(client, "case-3", key="idem-abc")
    second = _submit(client, "case-3", key="idem-abc")
    assert first["claim_id"] == second["claim_id"]
    assert first["idempotent_replay"] is False
    assert second["idempotent_replay"] is True


def test_distinct_keys_make_distinct_claims(client: TestClient) -> None:
    one = _submit(client, "case-4", key="k1")
    two = _submit(client, "case-4", key="k2")
    assert one["claim_id"] != two["claim_id"]


# --- status ----------------------------------------------------------------- #


def test_status_returns_decision(client: TestClient) -> None:
    client.post("/_control/labels", json={"case-5": {"outcome": "approved"}})
    claim = _submit(client, "case-5")["claim_id"]
    r = client.get(f"/status/{claim}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "approved"
    assert body["case_id"] == "case-5"


def test_status_unknown_is_404(client: TestClient) -> None:
    assert client.get("/status/PA-999999").status_code == 404


# --- failure modes (T3.2) --------------------------------------------------- #


def test_injected_429_then_success(client: TestClient) -> None:
    client.post("/_control/failures", json={"inject_statuses": [429]})
    r = client.post("/claims/prior-auth", json={"case_id": "case-6", "procedure": "knee_mri"})
    assert r.status_code == 429
    assert r.headers["Retry-After"] == "2"
    # Next request is served normally.
    assert _submit(client, "case-6")["status"] in {
        "approved",
        "denied",
        "pended",
        "more_info",
    }


def test_outage_returns_503(client: TestClient) -> None:
    client.post("/_control/failures", json={"outage": True})
    r = client.post("/claims/prior-auth", json={"case_id": "case-7", "procedure": "ct_abdomen"})
    assert r.status_code == 503


def test_plan_webhook_deliveries_duplicate_and_reorder() -> None:
    events = [1, 2, 3]
    assert plan_webhook_deliveries(events, FailureConfig()) == [1, 2, 3]
    assert plan_webhook_deliveries(events, FailureConfig(reorder_webhooks=True)) == [3, 2, 1]
    assert plan_webhook_deliveries(events, FailureConfig(duplicate_webhooks=True)) == [1, 2, 3, 3]
