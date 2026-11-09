"""Tests for clearance/policies/rules.py (T1.4) — one per rule type."""

from __future__ import annotations

from datetime import date
from typing import Any

from clearance.policies.rules import (
    AgeRule,
    ConservativeTherapyRule,
    DiagnosisRule,
    PatientFacts,
    PriorProcedureRule,
    build_facts,
    evaluate,
    parse_rule_spec,
)

AS_OF = date(2023, 1, 1)


def _condition(rid: str, code: str) -> dict[str, Any]:
    return {"resourceType": "Condition", "id": rid, "code": {"coding": [{"code": code}]}}


def _procedure(rid: str, code: str, when: str) -> dict[str, Any]:
    return {
        "resourceType": "Procedure",
        "id": rid,
        "code": {"coding": [{"code": code}]},
        "performedDateTime": when,
    }


def _medication(rid: str, code: str, when: str) -> dict[str, Any]:
    return {
        "resourceType": "MedicationRequest",
        "id": rid,
        "medicationCodeableConcept": {"coding": [{"code": code}]},
        "authoredOn": when,
    }


# --- age -------------------------------------------------------------------- #


def test_age_within_range_met() -> None:
    facts = PatientFacts(as_of=AS_OF, birth_date=date(1980, 6, 1))
    assert evaluate(AgeRule(min_years=18), facts).status == "met"


def test_age_below_min_not_met() -> None:
    facts = PatientFacts(as_of=AS_OF, birth_date=date(2010, 6, 1))
    res = evaluate(AgeRule(min_years=18), facts)
    assert res.status == "not_met"


def test_age_unknown_without_birthdate() -> None:
    facts = PatientFacts(as_of=AS_OF, birth_date=None)
    assert evaluate(AgeRule(min_years=18), facts).status == "unknown"


# --- diagnosis -------------------------------------------------------------- #


def test_diagnosis_match_met_with_evidence() -> None:
    facts = PatientFacts(as_of=AS_OF, conditions=[_condition("c1", "M54.5")])
    res = evaluate(DiagnosisRule(any_of=["M54.5", "M51.26"]), facts)
    assert res.status == "met"
    assert res.evidence_refs == ["c1"]


def test_diagnosis_absent_not_met() -> None:
    facts = PatientFacts(as_of=AS_OF, conditions=[_condition("c1", "J45.909")])
    assert evaluate(DiagnosisRule(any_of=["M54.5"]), facts).status == "not_met"


# --- prior procedure (within window) ---------------------------------------- #


def test_prior_procedure_present_in_window_met() -> None:
    facts = PatientFacts(as_of=AS_OF, procedures=[_procedure("p1", "72148", "2022-09-01")])
    res = evaluate(PriorProcedureRule(codes=["72148"], within_months=6), facts)
    assert res.status == "met"
    assert res.evidence_refs == ["p1"]


def test_prior_procedure_outside_window_not_met() -> None:
    facts = PatientFacts(as_of=AS_OF, procedures=[_procedure("p1", "72148", "2021-01-01")])
    res = evaluate(PriorProcedureRule(codes=["72148"], within_months=6), facts)
    assert res.status == "not_met"


def test_prior_procedure_must_be_absent_met_when_none() -> None:
    facts = PatientFacts(as_of=AS_OF, procedures=[])
    res = evaluate(
        PriorProcedureRule(codes=["72148"], within_months=12, must_be_absent=True), facts
    )
    assert res.status == "met"


def test_prior_procedure_must_be_absent_not_met_when_present() -> None:
    facts = PatientFacts(as_of=AS_OF, procedures=[_procedure("p1", "72148", "2022-12-01")])
    res = evaluate(
        PriorProcedureRule(codes=["72148"], within_months=12, must_be_absent=True), facts
    )
    assert res.status == "not_met"


# --- conservative therapy duration ------------------------------------------ #


def test_conservative_therapy_long_enough_met() -> None:
    facts = PatientFacts(as_of=AS_OF, medications=[_medication("m1", "198440", "2022-10-01")])
    res = evaluate(ConservativeTherapyRule(codes=["198440"], min_duration_days=42), facts)
    assert res.status == "met"  # ~92 days
    assert res.evidence_refs == ["m1"]


def test_conservative_therapy_too_short_not_met() -> None:
    facts = PatientFacts(as_of=AS_OF, medications=[_medication("m1", "198440", "2022-12-15")])
    res = evaluate(ConservativeTherapyRule(codes=["198440"], min_duration_days=42), facts)
    assert res.status == "not_met"  # ~17 days


def test_conservative_therapy_counts_procedures_too() -> None:
    facts = PatientFacts(as_of=AS_OF, procedures=[_procedure("pt1", "97110", "2022-01-01")])
    res = evaluate(ConservativeTherapyRule(codes=["97110"], min_duration_days=42), facts)
    assert res.status == "met"


# --- spec parsing + facts builder ------------------------------------------- #


def test_parse_rule_spec_discriminates_on_kind() -> None:
    spec = parse_rule_spec({"kind": "age", "min_years": 21})
    assert isinstance(spec, AgeRule)
    assert spec.min_years == 21


def test_build_facts_buckets_by_type() -> None:
    resources = [
        {"resourceType": "Patient", "id": "pat", "birthDate": "1980-06-01"},
        _condition("c1", "M54.5"),
        _procedure("p1", "72148", "2022-09-01"),
        _medication("m1", "198440", "2022-10-01"),
    ]
    facts = build_facts(resources, AS_OF)
    assert facts.birth_date == date(1980, 6, 1)
    assert len(facts.conditions) == 1
    assert len(facts.procedures) == 1
    assert len(facts.medications) == 1
