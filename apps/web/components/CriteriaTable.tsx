"use client";

import { CheckCircle2, CircleHelp, XCircle } from "lucide-react";
import clsx from "clsx";
import type { Criterion, Decision, EvidenceCard } from "@/lib/types";
import { statusTone } from "@/lib/ui";
import { Cite } from "./ui";

const ICON = {
  met: CheckCircle2,
  not_met: XCircle,
  unknown: CircleHelp,
};

export function CriteriaTable({
  checklist,
  decisions,
  evidence,
}: {
  checklist: Criterion[];
  decisions: Decision[];
  evidence: EvidenceCard[];
}) {
  const byId = new Map(decisions.map((d) => [d.criterion_id, d]));
  const evById = new Map(evidence.map((e) => [e.criterion_id, e]));

  return (
    <div className="card overflow-hidden">
      <div className="grid grid-cols-[1fr] divide-y divide-line">
        {checklist.map((c) => {
          const d = byId.get(c.id);
          const ev = evById.get(c.id);
          const status = d?.status ?? "unknown";
          const Icon = ICON[status];
          return (
            <div key={c.id} className="p-4 sm:p-5 flex gap-3.5 animate-fade-up">
              <Icon className={clsx("w-5 h-5 shrink-0 mt-0.5", statusTone(status))} />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2 justify-between">
                  <p className="font-medium leading-snug">{c.text}</p>
                  <div className="flex items-center gap-2 text-xs">
                    <span
                      className={clsx(
                        "pill",
                        d?.method === "rule"
                          ? "bg-zinc-100 text-zinc-600 dark:bg-zinc-500/15 dark:text-zinc-300"
                          : "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
                      )}
                    >
                      {d?.method === "rule" ? "deterministic rule" : "agent judgment"}
                    </span>
                    <span className={clsx("font-semibold capitalize", statusTone(status))}>
                      {status.replace("_", " ")}
                    </span>
                  </div>
                </div>
                {ev?.summary && (
                  <p className="mt-1.5 text-sm text-muted leading-relaxed">{ev.summary}</p>
                )}
                {d?.rationale && (
                  <p className="mt-1 text-sm text-muted/90 italic">{d.rationale}</p>
                )}
                <div className="mt-2 flex items-center gap-2 flex-wrap">
                  <span className="text-[11px] uppercase tracking-wide text-muted">Evidence</span>
                  {d?.evidence_refs?.length ? (
                    <Cite refs={d.evidence_refs} />
                  ) : (
                    <span className="text-xs text-amber-600 dark:text-amber-400">
                      no citation — flagged by verifier
                    </span>
                  )}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
