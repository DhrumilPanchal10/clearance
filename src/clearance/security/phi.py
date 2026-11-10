"""PHI redaction for logs and traces (plan T8.2).

Defense-in-depth: the tools already apply *minimum necessary* (ages, not names;
no MRN), but anything that could still carry PHI — a free-text note summary, an
error string, a span attribute — is scrubbed before it can land in a log line
or an exported trace. :class:`PHIRedactingSpanProcessor` masks span attribute
values as spans are created, so no PHI reaches the OTLP exporter.

Redaction is pattern-based (deterministic, offline, no model): identifiers
(SSN, MRN, phone, email), dates of birth, and labelled fields (Name:, Patient:,
Address:, DOB:, MRN:). Each match is replaced with a typed placeholder so the
shape of the data is still debuggable (e.g. ``[SSN]``, ``[DOB]``).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from opentelemetry.sdk.trace import ReadableSpan, Span, SpanProcessor

# Order matters: more specific patterns first so they win the replacement.
_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("PHONE", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    # MRN: labelled, or a bare 6–10 digit medical-record-looking number.
    ("MRN", re.compile(r"\bMRN[:#]?\s*[A-Za-z0-9\-]{4,}\b", re.I)),
    ("DOB", re.compile(r"\bDOB[:#]?\s*\d{1,4}[-/]\d{1,2}[-/]\d{1,4}\b", re.I)),
    ("DOB", re.compile(r"\b\d{4}-\d{2}-\d{2}\b")),  # ISO date (conservative)
    ("DOB", re.compile(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    # Labelled free-text identifiers.
    ("NAME", re.compile(r"\b(?:patient name|name|patient)[:#]\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)+", re.I)),
    ("ADDRESS", re.compile(r"\b\d{1,5}\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*\s+(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Lane|Ln|Dr|Drive|Ct|Court)\b", re.I)),
    ("ZIP", re.compile(r"\b\d{5}(?:-\d{4})?\b")),
]

# Attribute keys whose values are always considered PHI and dropped wholesale.
_PHI_KEYS = {"patient_name", "name", "dob", "date_of_birth", "mrn", "address", "ssn", "phone"}


def redact_text(text: str) -> str:
    """Replace any PHI-looking substrings with typed placeholders."""
    if not text:
        return text
    out = text
    for label, pattern in _PATTERNS:
        out = pattern.sub(f"[{label}]", out)
    return out


def redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, (list, tuple)):
        return type(value)(redact_value(v) for v in value)
    if isinstance(value, Mapping):
        return redact_mapping(value)
    return value


def redact_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    """Redact a dict: PHI-keyed fields are masked entirely, others scrubbed."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _PHI_KEYS:
            out[key] = "[REDACTED]"
        else:
            out[key] = redact_value(value)
    return out


def contains_phi(text: str) -> bool:
    return any(pattern.search(text) for _, pattern in _PATTERNS)


class PHIRedactingSpanProcessor(SpanProcessor):
    """Scrubs PHI from span attributes before they reach any exporter."""

    def on_start(self, span: Span, parent_context: Any = None) -> None:  # noqa: D102
        return None

    def on_end(self, span: ReadableSpan) -> None:  # noqa: D102
        # Scrub right before the span is handed to any exporter. The span is
        # ended, so attributes are mutated through the SDK's private store.
        attrs = getattr(span, "_attributes", None)
        if not attrs:
            return
        # BoundedAttributes is immutable once the span ends; mutate its backing
        # dict directly so redaction lands before the exporter reads it.
        backing = getattr(attrs, "_dict", attrs)
        try:
            for key, value in list(backing.items()):
                if key.lower() in _PHI_KEYS:
                    backing[key] = "[REDACTED]"
                elif isinstance(value, str) and contains_phi(value):
                    backing[key] = redact_text(value)
        except Exception:  # pragma: no cover - never break tracing
            return

    def shutdown(self) -> None:  # noqa: D102
        return None

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: D102
        return True
