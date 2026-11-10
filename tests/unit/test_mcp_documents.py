"""Tests for the documents MCP tool (T4.5)."""

from __future__ import annotations

from pathlib import Path

from agentcore.audit import AuditLog
from agentcore.auth import UserClaims
from clearance.mcp_servers.base import ToolContext
from clearance.mcp_servers.documents import (
    LetterDraft,
    LetterLine,
    LetterSection,
    build_document_tools,
    cited_refs,
    render_pdf,
    uncited_lines,
)


def _draft() -> LetterDraft:
    return LetterDraft(
        title="Letter of Medical Necessity",
        payer="medicare",
        procedure="lumbar_spine_mri",
        patient_ref="Patient/pat-001",
        sections=[
            LetterSection(
                heading="Clinical History",
                lines=[
                    LetterLine(text="Chronic low back pain for 10 weeks.", fhir_refs=["cond-1"]),
                    LetterLine(
                        text="Completed 8 weeks of physical therapy.", fhir_refs=["proc-1", "med-1"]
                    ),
                    LetterLine(text="Pain limits daily function."),  # uncited
                ],
            )
        ],
    )


def _ctx() -> ToolContext:
    return ToolContext(
        claims=UserClaims(user_id="u1", tenant_id="clinic-a", role="coordinator", raw={}),
        clinic_id="clinic-a",
    )


def test_render_pdf_produces_pdf_bytes() -> None:
    data = render_pdf(_draft())
    assert data[:5] == b"%PDF-"
    assert len(data) > 500


def test_cited_and_uncited_helpers() -> None:
    draft = _draft()
    assert cited_refs(draft) == {"cond-1", "proc-1", "med-1"}
    assert uncited_lines(draft) == ["Pain limits daily function."]


async def test_render_letter_tool_writes_file(tmp_path: Path) -> None:
    tools = build_document_tools(AuditLog(), tmp_path)
    result = await tools.render_letter(_ctx(), case_id="case-1", draft=_draft().model_dump())
    out = Path(result["path"])
    assert out.exists() and out.read_bytes()[:5] == b"%PDF-"
    assert result["cited_refs"] == ["cond-1", "med-1", "proc-1"]
    # The verifier will block submission on these uncited clinical lines.
    assert result["uncited_lines"] == ["Pain limits daily function."]
