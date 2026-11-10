"""Deterministic rules engine for rule-checkable criteria (plan T1.4).

Rule-checkable criteria (age, diagnosis code sets, prior-imaging windows,
conservative-therapy duration) are evaluated here in Python — never by a model.
Each result carries the FHIR resource ids it relied on, so downstream drafting
can cite them.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

RuleStatus = Literal["met", "not_met", "unknown"]


@dataclass(slots=True)
class PatientFacts:
    """The minimum-necessary chart slice a rule evaluates against."""

    as_of: date
    birth_date: date | None = None
    conditions: list[dict[str, Any]] = field(default_factory=list)
    procedures: list[dict[str, Any]] = field(default_factory=list)
    medications: list[dict[str, Any]] = field(default_factory=list)
    observations: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class RuleResult:
    status: RuleStatus
    detail: str
    evidence_refs: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Rule specs (a discriminated union on ``kind``). T1.3 emits these as JSON.
# --------------------------------------------------------------------------- #


class AgeRule(BaseModel):
    kind: Literal["age"] = "age"
    min_years: int | None = None
    max_years: int | None = None


class DiagnosisRule(BaseModel):
    kind: Literal["diagnosis"] = "diagnosis"
    any_of: list[str]  # ICD-10 / SNOMED codes
    # False: met when at least one code is present (an indication).
    # True: met when NONE are present (a contraindication, e.g. "no pregnancy").
    must_be_absent: bool = False


class PriorProcedureRule(BaseModel):
    kind: Literal["prior_procedure"] = "prior_procedure"
    codes: list[str]
    within_months: int
    # True: criterion requires that NO such procedure occurred in the window
    # (e.g. "no repeat MRI within 12 months"). False: requires one did.
    must_be_absent: bool = False


class ConservativeTherapyRule(BaseModel):
    kind: Literal["conservative_therapy"] = "conservative_therapy"
    # Match either a MedicationRequest or a Procedure carrying one of these codes.
    codes: list[str]
    min_duration_days: int


RuleSpec = Annotated[
    AgeRule | DiagnosisRule | PriorProcedureRule | ConservativeTherapyRule,
    Field(discriminator="kind"),
]


class _RuleSpecModel(BaseModel):
    spec: RuleSpec


def parse_rule_spec(data: dict[str, Any]) -> RuleSpec:
    """Parse a JSON rule_spec (from a Criterion) into a typed RuleSpec."""
    return _RuleSpecModel(spec=data).spec  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _codes_of(resource: dict[str, Any], *keys: str) -> set[str]:
    out: set[str] = set()
    for key in keys or ("code",):
        concept = resource.get(key)
        if isinstance(concept, dict):
            for coding in concept.get("coding", []) or []:
                code = coding.get("code")
                if isinstance(code, str):
                    out.add(code)
    return out


def _resource_date(resource: dict[str, Any], *fields: str) -> date | None:
    for fname in fields:
        value = resource.get(fname)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                continue
        if isinstance(value, dict) and isinstance(value.get("start"), str):
            try:
                return datetime.fromisoformat(value["start"].replace("Z", "+00:00")).date()
            except ValueError:
                continue
    return None


def _months_before(anchor: date, months: int) -> date:
    total = (anchor.year * 12 + (anchor.month - 1)) - months
    year, month = divmod(total, 12)
    day = min(anchor.day, [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month])
    return date(year, month + 1, day)


def _age_years(birth: date, as_of: date) -> int:
    return as_of.year - birth.year - ((as_of.month, as_of.day) < (birth.month, birth.day))


def _any_code_match(
    resources: Iterable[dict[str, Any]], codes: Sequence[str], *keys: str
) -> list[dict[str, Any]]:
    wanted = set(codes)
    return [r for r in resources if _codes_of(r, *keys) & wanted]


# --------------------------------------------------------------------------- #
# Evaluation
# --------------------------------------------------------------------------- #


def _eval_age(rule: AgeRule, facts: PatientFacts) -> RuleResult:
    if facts.birth_date is None:
        return RuleResult("unknown", "no birthDate on record")
    age = _age_years(facts.birth_date, facts.as_of)
    if rule.min_years is not None and age < rule.min_years:
        return RuleResult("not_met", f"age {age} < min {rule.min_years}")
    if rule.max_years is not None and age > rule.max_years:
        return RuleResult("not_met", f"age {age} > max {rule.max_years}")
    return RuleResult("met", f"age {age} within range")


def _eval_diagnosis(rule: DiagnosisRule, facts: PatientFacts) -> RuleResult:
    matches = _any_code_match(facts.conditions, rule.any_of)
    refs = [m["id"] for m in matches if "id" in m]
    if rule.must_be_absent:
        if matches:
            return RuleResult(
                "not_met", f"contraindicating diagnosis present ({len(matches)})", refs
            )
        return RuleResult("met", "no contraindicating diagnosis")
    if matches:
        return RuleResult("met", f"diagnosis code present ({len(matches)})", refs)
    return RuleResult("not_met", "no matching diagnosis code")


def _eval_prior_procedure(rule: PriorProcedureRule, facts: PatientFacts) -> RuleResult:
    cutoff = _months_before(facts.as_of, rule.within_months)
    in_window: list[dict[str, Any]] = []
    for proc in _any_code_match(facts.procedures, rule.codes):
        pdate = _resource_date(proc, "performedDateTime", "performedPeriod")
        if pdate is not None and cutoff <= pdate <= facts.as_of:
            in_window.append(proc)
    refs = [p["id"] for p in in_window if "id" in p]
    if rule.must_be_absent:
        if in_window:
            return RuleResult(
                "not_met", f"{len(in_window)} procedure(s) within {rule.within_months}mo", refs
            )
        return RuleResult("met", f"none within {rule.within_months}mo")
    if in_window:
        return RuleResult(
            "met", f"{len(in_window)} procedure(s) within {rule.within_months}mo", refs
        )
    return RuleResult("not_met", f"none within {rule.within_months}mo")


def _eval_conservative_therapy(rule: ConservativeTherapyRule, facts: PatientFacts) -> RuleResult:
    dated: list[tuple[date, str]] = []
    for med in _any_code_match(facts.medications, rule.codes, "medicationCodeableConcept"):
        mdate = _resource_date(med, "authoredOn")
        if mdate is not None and "id" in med:
            dated.append((mdate, med["id"]))
    for proc in _any_code_match(facts.procedures, rule.codes):
        pdate = _resource_date(proc, "performedDateTime", "performedPeriod")
        if pdate is not None and "id" in proc:
            dated.append((pdate, proc["id"]))

    if not dated:
        return RuleResult("not_met", "no conservative therapy on record")
    earliest = min(d for d, _ in dated)
    duration = (facts.as_of - earliest).days
    refs = [rid for _, rid in sorted(dated)]
    if duration >= rule.min_duration_days:
        return RuleResult("met", f"{duration}d >= {rule.min_duration_days}d", refs)
    return RuleResult("not_met", f"{duration}d < {rule.min_duration_days}d", refs)


_DISPATCH: dict[str, Callable[[Any, PatientFacts], RuleResult]] = {
    "age": _eval_age,
    "diagnosis": _eval_diagnosis,
    "prior_procedure": _eval_prior_procedure,
    "conservative_therapy": _eval_conservative_therapy,
}


def evaluate(spec: RuleSpec, facts: PatientFacts) -> RuleResult:
    """Evaluate one rule spec against a patient's facts."""
    return _DISPATCH[spec.kind](spec, facts)


def build_facts(resources: Iterable[dict[str, Any]], as_of: date) -> PatientFacts:
    """Bucket raw FHIR resource dicts into a PatientFacts for evaluation."""
    facts = PatientFacts(as_of=as_of)
    for r in resources:
        match r.get("resourceType"):
            case "Patient":
                bd = r.get("birthDate")
                facts.birth_date = date.fromisoformat(bd) if isinstance(bd, str) else None
            case "Condition":
                facts.conditions.append(r)
            case "Procedure":
                facts.procedures.append(r)
            case "MedicationRequest":
                facts.medications.append(r)
            case "Observation":
                facts.observations.append(r)
    return facts
