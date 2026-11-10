"""documents MCP server (plan T4.5).

Renders a structured letter of medical necessity / appeal draft to PDF. Every
clinical line carries the FHIR resource ids it is grounded in; those citations
are printed inline and also returned, so the verifier (T5.6) can gate on them.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal

from fpdf import FPDF
from fpdf.enums import XPos, YPos
from pydantic import BaseModel, Field

from agentcore.audit import AuditLog
from clearance.mcp_servers.base import Risk, ToolContext, mcp_tool

_RENDER_ROLES = frozenset({"coordinator", "clinician", "manager"})


class LetterLine(BaseModel):
    text: str
    # FHIR resource ids supporting this clinical statement. Empty = uncited.
    fhir_refs: list[str] = Field(default_factory=list)


class LetterSection(BaseModel):
    heading: str
    lines: list[LetterLine]


class LetterDraft(BaseModel):
    kind: Literal["letter_of_medical_necessity", "appeal"] = "letter_of_medical_necessity"
    title: str
    payer: str
    procedure: str
    patient_ref: str
    sections: list[LetterSection]


def cited_refs(draft: LetterDraft) -> set[str]:
    """All FHIR ids cited anywhere in the draft."""
    return {ref for sec in draft.sections for line in sec.lines for ref in line.fhir_refs}


def uncited_lines(draft: LetterDraft) -> list[str]:
    """Clinical lines with no FHIR citation (the verifier blocks on these)."""
    return [line.text for sec in draft.sections for line in sec.lines if not line.fhir_refs]


def _citation(line: LetterLine) -> str:
    return "  " + " ".join(f"[fhir:{r}]" for r in line.fhir_refs) if line.fhir_refs else ""


def render_pdf(draft: LetterDraft) -> bytes:
    """Render a draft to PDF bytes (pure; no I/O)."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()

    def write(text: str, height: float) -> None:
        # Return the cursor to the left margin on a new line each time.
        pdf.multi_cell(0, height, text, new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    pdf.set_font("Helvetica", style="B", size=16)
    write(draft.title, 10)
    pdf.set_font("Helvetica", size=10)
    write(f"Payer: {draft.payer}    Procedure: {draft.procedure}", 6)
    write(f"Patient: {draft.patient_ref}", 6)
    pdf.ln(4)

    for section in draft.sections:
        pdf.set_font("Helvetica", style="B", size=12)
        write(section.heading, 8)
        pdf.set_font("Helvetica", size=11)
        for line in section.lines:
            write(f"{line.text}{_citation(line)}", 6)
        pdf.ln(2)

    return bytes(pdf.output())


def build_document_tools(audit_log: AuditLog, out_dir: str | Path) -> SimpleNamespace:
    out = Path(out_dir)

    @mcp_tool("render_letter", allowed_roles=_RENDER_ROLES, risk=Risk.READ, audit_log=audit_log)
    async def render_letter(
        ctx: ToolContext, *, case_id: str, draft: dict[str, Any]
    ) -> dict[str, Any]:
        model = LetterDraft.model_validate(draft)
        pdf_bytes = render_pdf(model)
        out.mkdir(parents=True, exist_ok=True)
        path = out / f"{case_id}_{model.kind}.pdf"
        path.write_bytes(pdf_bytes)
        return {
            "path": str(path),
            "bytes": len(pdf_bytes),
            "cited_refs": sorted(cited_refs(model)),
            "uncited_lines": uncited_lines(model),
        }

    return SimpleNamespace(render_letter=render_letter)
