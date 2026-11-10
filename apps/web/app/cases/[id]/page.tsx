"use client";

import { use } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CircleDollarSign,
  FileCheck2,
  Hash,
  ScrollText,
  Stethoscope,
} from "lucide-react";
import { useCase } from "@/lib/useCase";
import { procedureLabel, money } from "@/lib/ui";
import {
  ConfidenceMeter,
  EmptyState,
  OutcomeBadge,
  Spinner,
  StageBadge,
} from "@/components/ui";
import { Timeline } from "@/components/Timeline";
import { CriteriaTable } from "@/components/CriteriaTable";
import { LetterPreview } from "@/components/LetterPreview";
import { CaseActions } from "@/components/CaseActions";

export default function CasePage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, live, refetch } = useCase(id);

  if (error) {
    return (
      <div>
        <BackLink />
        <EmptyState title="Case unavailable" body={error} />
      </div>
    );
  }
  if (!data) return <Spinner label="Loading case…" />;

  // Prefer the server timeline; fall back to the live SSE buffer.
  const timeline = data.timeline?.length ? data.timeline : live;
  const metCount = data.decisions.filter((d) => d.status === "met").length;

  return (
    <div>
      <BackLink />

      {/* Header */}
      <div className="card p-5 lg:p-6 mb-5">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <div className="flex items-center gap-2.5 flex-wrap">
              <h1 className="text-xl lg:text-2xl font-semibold tracking-tight">
                {procedureLabel(data.procedure)}
              </h1>
              {data.outcome ? (
                <OutcomeBadge outcome={data.outcome} />
              ) : (
                <StageBadge stage={data.stage} />
              )}
            </div>
            <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
              <span className="inline-flex items-center gap-1.5">
                <Stethoscope className="w-3.5 h-3.5" /> {data.payer}
              </span>
              <span className="inline-flex items-center gap-1.5 font-mono">
                <Hash className="w-3.5 h-3.5" /> {data.patient_id}
              </span>
              <span className="inline-flex items-center gap-1.5">
                <ScrollText className="w-3.5 h-3.5" /> Policy {data.policy_version ?? "—"}
              </span>
            </div>
          </div>
          <div className="grid grid-cols-3 gap-4 text-sm">
            <Metric label="Criteria met" value={`${metCount}/${data.decisions.length}`} />
            <Metric
              label="Confidence"
              value={<ConfidenceMeter value={data.confidence} />}
            />
            <Metric label="Agent cost" value={money(data.est_cost_usd)} icon={<CircleDollarSign className="w-3.5 h-3.5" />} />
          </div>
        </div>
        {data.denial_reason && data.outcome !== "approved" && (
          <div className="mt-4 rounded-lg bg-rose-50 dark:bg-rose-500/10 border border-rose-200 dark:border-rose-500/20 px-4 py-2.5 text-sm text-rose-700 dark:text-rose-300">
            Payer denial reason: <span className="font-medium">{data.denial_reason}</span>
            {data.appeal_cycles > 0 && ` · appeal cycle ${data.appeal_cycles}`}
          </div>
        )}
      </div>

      <div className="grid lg:grid-cols-[1fr_340px] gap-5 items-start">
        {/* Left: criteria + letter */}
        <div className="space-y-5 order-2 lg:order-1">
          <section>
            <h2 className="flex items-center gap-2 text-sm font-semibold text-muted uppercase tracking-wide mb-3">
              <FileCheck2 className="w-4 h-4" /> Evidence vs. criteria
            </h2>
            {data.checklist.length ? (
              <CriteriaTable
                checklist={data.checklist}
                decisions={data.decisions}
                evidence={data.evidence_cards}
              />
            ) : (
              <div className="card p-6 text-sm text-muted">
                Assessing the chart against the policy checklist…
              </div>
            )}
          </section>

          <section>
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-3">
              Draft
            </h2>
            <LetterPreview detail={data} />
          </section>
        </div>

        {/* Right: actions + timeline */}
        <div className="space-y-5 order-1 lg:order-2 lg:sticky lg:top-20">
          <CaseActions detail={data} onDone={refetch} />
          <div className="card p-5">
            <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-4">
              Live timeline
            </h2>
            <Timeline events={timeline} />
          </div>
        </div>
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  icon?: React.ReactNode;
}) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted flex items-center gap-1">
        {icon}
        {label}
      </div>
      <div className="mt-1 font-semibold tabular-nums">{value}</div>
    </div>
  );
}

function BackLink() {
  return (
    <Link
      href="/cases"
      className="inline-flex items-center gap-1.5 text-sm text-muted hover:text-ink mb-4"
    >
      <ArrowLeft className="w-4 h-4" /> Back to queue
    </Link>
  );
}
