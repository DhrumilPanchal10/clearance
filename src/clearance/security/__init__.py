"""Security hardening for Clearance (plan Phase 8).

- :mod:`clearance.security.phi` — PHI redaction for logs and traces (T8.2).
- :mod:`clearance.security.injection` — untrusted clinical-note screening (T8.3).
- :mod:`clearance.security.rls` — row-level clinic isolation (T8.1).
"""

from clearance.security.injection import NoteScreen, neutralize_note, screen_note
from clearance.security.phi import PHIRedactingSpanProcessor, redact_mapping, redact_text

__all__ = [
    "NoteScreen",
    "PHIRedactingSpanProcessor",
    "neutralize_note",
    "redact_mapping",
    "redact_text",
    "screen_note",
]
