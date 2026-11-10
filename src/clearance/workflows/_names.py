"""Activity + signal/query names shared by the workflow and the activities.

Kept dependency-free so the workflow can import it inside Temporal's sandbox
without pulling in I/O libraries.
"""

from __future__ import annotations

# Activity names
ASSESS = "assess_case"
DRAFT = "draft_case"
SUBMIT = "submit_case"
APPEAL = "appeal_case"

# Signal names
SIG_CLINICIAN_ANSWER = "clinician_answer"
SIG_COORDINATOR_DECISION = "coordinator_decision"
SIG_PAYER_UPDATE = "payer_update"

# Query names
QRY_CURRENT_STATE = "current_state"
