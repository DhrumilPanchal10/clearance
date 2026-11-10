"use client";

import { useEffect, useState } from "react";
import { BookOpen, ShieldCheck, TrendingUp } from "lucide-react";
import { api } from "@/lib/api";
import type { PlaybookNote } from "@/lib/types";
import { useSession } from "@/app/providers";
import { useCases } from "@/lib/useCases";
import { PageHeader } from "@/components/PageHeader";
import { CaseList } from "@/components/CaseList";
import { EmptyState, Spinner } from "@/components/ui";
import { procedureLabel } from "@/lib/ui";

export default function ManagerPage() {
  const { session, ready } = useSession();
  const { cases, loading } = useCases({ mine_role: "manager" });
  const [notes, setNotes] = useState<PlaybookNote[]>([]);

  useEffect(() => {
    if (!ready) return;
    api
      .playbook(session)
      .then((r) => setNotes(r.notes))
      .catch(() => setNotes([]));
  }, [ready, session]);

  return (
    <div>
      <PageHeader
        title="Manager & payer playbook"
        subtitle="Cases escalated for a second set of eyes, plus the institutional memory the agent consults before every submission."
      />

      <h2 className="flex items-center gap-2 text-sm font-semibold text-muted uppercase tracking-wide mb-3">
        <ShieldCheck className="w-4 h-4" /> Escalated for manager review
      </h2>
      {loading ? (
        <Spinner />
      ) : cases.length === 0 ? (
        <EmptyState title="No escalations" body="No cases need a manager decision right now." />
      ) : (
        <CaseList cases={cases} />
      )}

      <h2 className="flex items-center gap-2 text-sm font-semibold text-muted uppercase tracking-wide mb-3 mt-8">
        <BookOpen className="w-4 h-4" /> Per-payer playbook
        <span className="font-normal normal-case text-xs text-muted">
          learned from past outcomes · expires on policy change
        </span>
      </h2>
      {notes.length === 0 ? (
        <EmptyState
          title="No playbook notes yet"
          body="After a few cases reach a payer decision, nightly consolidation distills what tends to get approved vs. denied for each payer and procedure."
          icon={<TrendingUp className="w-8 h-8 mx-auto" />}
        />
      ) : (
        <div className="grid md:grid-cols-2 gap-4">
          {notes.map((n) => {
            const total = n.approvals + n.denials;
            const rate = total ? Math.round((n.approvals / total) * 100) : 0;
            return (
              <div key={`${n.payer}:${n.procedure}`} className="card p-5 animate-fade-up">
                <div className="flex items-center justify-between">
                  <div>
                    <div className="font-semibold">{procedureLabel(n.procedure)}</div>
                    <div className="text-xs text-muted">
                      {n.payer} · policy {n.policy_version ?? "—"}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-semibold tabular-nums text-emerald-600 dark:text-emerald-400">
                      {rate}%
                    </div>
                    <div className="text-[11px] text-muted">
                      {n.approvals}✓ / {n.denials}✗
                    </div>
                  </div>
                </div>
                <p className="mt-3 text-sm leading-relaxed">{n.guidance}</p>
                {n.top_denial_reasons.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {n.top_denial_reasons.map(([reason, count]) => (
                      <span
                        key={reason}
                        className="pill bg-rose-100 text-rose-700 dark:bg-rose-500/15 dark:text-rose-300"
                      >
                        {reason.replace(/_/g, " ")} ×{count}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
