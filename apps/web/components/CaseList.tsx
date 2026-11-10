"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { CaseSummary } from "@/lib/types";
import { money, procedureLabel, timeAgo } from "@/lib/ui";
import { ConfidenceMeter, OutcomeBadge, StageBadge } from "./ui";

export function CaseList({ cases }: { cases: CaseSummary[] }) {
  return (
    <div className="card overflow-hidden">
      <div className="hidden md:grid grid-cols-[1.4fr_1fr_1fr_0.9fr_0.7fr_auto] gap-4 px-5 py-3 text-[11px] font-semibold uppercase tracking-wide text-muted border-b border-line">
        <span>Patient / procedure</span>
        <span>Stage</span>
        <span>Criteria</span>
        <span>Confidence</span>
        <span>Cost</span>
        <span className="sr-only">open</span>
      </div>
      <ul className="divide-y divide-line">
        {cases.map((c) => (
          <li key={c.case_id}>
            <Link
              href={`/cases/${c.case_id}`}
              className="grid md:grid-cols-[1.4fr_1fr_1fr_0.9fr_0.7fr_auto] gap-x-4 gap-y-2 px-5 py-4 items-center hover:bg-bg transition-colors group"
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium truncate">{procedureLabel(c.procedure)}</span>
                  {c.needs_manager && (
                    <span className="pill bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300">
                      manager
                    </span>
                  )}
                </div>
                <div className="text-xs text-muted truncate">
                  <span className="font-mono">{c.patient_id}</span> · {c.payer} ·{" "}
                  {timeAgo(c.updated_at)}
                </div>
              </div>
              <div>
                {c.outcome ? <OutcomeBadge outcome={c.outcome} /> : <StageBadge stage={c.stage} />}
              </div>
              <div className="text-sm tabular-nums">
                <span className="font-semibold text-emerald-600 dark:text-emerald-400">
                  {c.criteria_met}
                </span>
                <span className="text-muted"> / {c.criteria_total} met</span>
              </div>
              <ConfidenceMeter value={c.confidence} />
              <div className="text-sm tabular-nums text-muted">{money(c.est_cost_usd)}</div>
              <ChevronRight className="w-4 h-4 text-muted group-hover:text-brand hidden md:block" />
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}
