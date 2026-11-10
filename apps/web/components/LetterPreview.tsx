"use client";

import { FileText } from "lucide-react";
import type { CaseDetail } from "@/lib/types";
import { procedureLabel } from "@/lib/ui";
import { Cite } from "./ui";

export function LetterPreview({ detail }: { detail: CaseDetail }) {
  const letter = detail.letter;
  if (!letter) {
    return (
      <div className="card p-6 text-sm text-muted">
        The medical-necessity letter is drafted after assessment completes.
      </div>
    );
  }
  const sections = letter.sections ?? [];
  return (
    <div className="card overflow-hidden">
      <div className="px-6 py-5 border-b border-line bg-gradient-to-br from-brand-soft/60 to-transparent">
        <div className="flex items-center gap-2 text-brand">
          <FileText className="w-4 h-4" />
          <span className="text-xs font-semibold uppercase tracking-wide">
            Letter of Medical Necessity
          </span>
        </div>
        <h3 className="mt-1.5 text-lg font-semibold tracking-tight">
          {letter.title ?? `${procedureLabel(detail.procedure)} — Prior Authorization`}
        </h3>
        <p className="text-sm text-muted">
          {detail.payer} · Policy {detail.policy_version ?? "—"} · Patient{" "}
          <span className="font-mono">{detail.patient_id}</span>
        </p>
      </div>
      <div className="p-6 space-y-5 text-[15px] leading-relaxed max-w-prose">
        {sections.length === 0 && (
          <p className="text-sm text-muted">Letter body renders here once drafted.</p>
        )}
        {sections.map((s, i) => (
          <section key={i}>
            <h4 className="font-semibold mb-1.5">{s.heading}</h4>
            <ul className="space-y-1.5">
              {s.lines.map((ln, j) => (
                <li key={j} className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                  <span>{ln.text}</span>
                  <Cite refs={ln.fhir_refs ?? []} />
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
