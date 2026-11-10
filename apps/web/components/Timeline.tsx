"use client";

import clsx from "clsx";
import {
  CircleDot,
  FileText,
  Gavel,
  Send,
  ShieldQuestion,
  Sparkles,
  UserCheck,
} from "lucide-react";
import type { TimelineEvent } from "@/lib/types";
import { timeAgo } from "@/lib/ui";

const KIND_ICON: Record<string, typeof CircleDot> = {
  stage: Sparkles,
  decision: FileText,
  human: UserCheck,
  payer: Send,
  error: ShieldQuestion,
};

function iconFor(ev: TimelineEvent) {
  if (ev.stage === "appealing") return Gavel;
  return KIND_ICON[ev.kind] ?? CircleDot;
}

export function Timeline({ events }: { events: TimelineEvent[] }) {
  if (!events.length) {
    return <p className="text-sm text-muted">Waiting for the first event…</p>;
  }
  return (
    <ol className="relative pl-6">
      <span className="absolute left-[9px] top-1 bottom-1 w-px bg-line" />
      {events.map((ev, i) => {
        const Icon = iconFor(ev);
        const last = i === events.length - 1;
        return (
          <li key={ev.seq} className="relative pb-5 last:pb-0 animate-fade-up">
            <span
              className={clsx(
                "absolute -left-6 grid place-items-center w-[19px] h-[19px] rounded-full ring-4 ring-bg",
                ev.kind === "error"
                  ? "bg-rose-500 text-white"
                  : last
                    ? "bg-brand text-white"
                    : "bg-card border border-line text-muted"
              )}
            >
              <Icon className="w-2.5 h-2.5" />
            </span>
            <div className="flex items-baseline justify-between gap-3">
              <p className="text-sm font-medium leading-snug">{ev.message}</p>
              <time className="text-[11px] text-muted shrink-0 tabular-nums">
                {timeAgo(ev.at)}
              </time>
            </div>
            {ev.kind === "payer" && ev.data?.status != null && (
              <p className="text-xs text-muted mt-0.5">
                payer status: <span className="font-mono">{String(ev.data.status)}</span>
              </p>
            )}
            {typeof ev.data?.guidance === "string" && (
              <p className="text-xs text-muted mt-0.5 italic">{ev.data.guidance}</p>
            )}
          </li>
        );
      })}
    </ol>
  );
}
