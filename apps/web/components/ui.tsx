"use client";

import clsx from "clsx";
import { Loader2 } from "lucide-react";
import type { Outcome, Stage } from "@/lib/types";
import { confidenceTone, outcomeTone, STAGE_LABEL, stageTone } from "@/lib/ui";

export function StageBadge({ stage }: { stage: Stage }) {
  const live = ["assessing", "drafting", "submitting", "tracking", "appealing"].includes(stage);
  return (
    <span className={clsx("pill", stageTone(stage))}>
      {live && <span className="w-1.5 h-1.5 rounded-full bg-current animate-pulse-dot" />}
      {STAGE_LABEL[stage]}
    </span>
  );
}

export function OutcomeBadge({ outcome }: { outcome: Outcome }) {
  if (!outcome) return null;
  return <span className={clsx("pill capitalize", outcomeTone(outcome))}>{outcome}</span>;
}

export function ConfidenceMeter({ value, className }: { value: number; className?: string }) {
  const pct = Math.round(value * 100);
  return (
    <div className={clsx("flex items-center gap-2", className)}>
      <div className="relative h-1.5 w-20 rounded-full bg-line overflow-hidden">
        <div
          className={clsx("absolute inset-y-0 left-0 rounded-full", confidenceTone(value))}
          style={{ width: `${pct}%` }}
        />
      </div>
      <span className="text-xs tabular-nums text-muted">{pct}%</span>
    </div>
  );
}

export function StatCard({
  label,
  value,
  hint,
  accent,
  icon,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  accent?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="card p-4 animate-fade-up">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted uppercase tracking-wide">{label}</span>
        {icon && <span className={clsx("opacity-80", accent)}>{icon}</span>}
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums tracking-tight">{value}</div>
      {hint && <div className="mt-1 text-xs text-muted">{hint}</div>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted py-8 justify-center">
      <Loader2 className="w-4 h-4 animate-spin" />
      {label ?? "Loading…"}
    </div>
  );
}

export function EmptyState({
  title,
  body,
  icon,
}: {
  title: string;
  body?: string;
  icon?: React.ReactNode;
}) {
  return (
    <div className="card p-10 text-center">
      {icon && <div className="mx-auto mb-3 text-muted">{icon}</div>}
      <div className="font-medium">{title}</div>
      {body && <div className="mt-1 text-sm text-muted max-w-sm mx-auto">{body}</div>}
    </div>
  );
}

export function Cite({ refs }: { refs: string[] }) {
  if (!refs?.length) return null;
  return (
    <span className="inline-flex flex-wrap gap-1 align-middle">
      {refs.map((r) => (
        <span
          key={r}
          title={`FHIR resource ${r}`}
          className="pill bg-brand-soft text-brand font-mono text-[10px] px-1.5 py-0.5"
        >
          {r}
        </span>
      ))}
    </span>
  );
}
