import type { Outcome, Stage } from "./types";

export const PROCEDURES: { value: string; label: string }[] = [
  { value: "lumbar_spine_mri", label: "Lumbar Spine MRI" },
  { value: "knee_mri", label: "Knee MRI" },
  { value: "ct_abdomen", label: "CT Abdomen / Pelvis" },
];

export function procedureLabel(value: string): string {
  return PROCEDURES.find((p) => p.value === value)?.label ?? value;
}

export const STAGE_LABEL: Record<Stage, string> = {
  created: "Created",
  assessing: "Assessing",
  awaiting_clinician: "Awaiting clinician",
  drafting: "Drafting letter",
  awaiting_approval: "Awaiting approval",
  submitting: "Submitting",
  tracking: "Tracking payer",
  appealing: "Appealing",
  done: "Complete",
  error: "Error",
};

// tone => tailwind classes for pills
export function stageTone(stage: Stage): string {
  switch (stage) {
    case "awaiting_approval":
      return "bg-amber-100 text-amber-800 dark:bg-amber-500/15 dark:text-amber-300";
    case "awaiting_clinician":
      return "bg-sky-100 text-sky-800 dark:bg-sky-500/15 dark:text-sky-300";
    case "done":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300";
    case "error":
      return "bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300";
    case "appealing":
      return "bg-fuchsia-100 text-fuchsia-800 dark:bg-fuchsia-500/15 dark:text-fuchsia-300";
    default:
      return "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300";
  }
}

export function outcomeTone(outcome: Outcome): string {
  switch (outcome) {
    case "approved":
      return "bg-emerald-100 text-emerald-800 dark:bg-emerald-500/15 dark:text-emerald-300";
    case "denied":
      return "bg-rose-100 text-rose-800 dark:bg-rose-500/15 dark:text-rose-300";
    case "rejected":
      return "bg-zinc-200 text-zinc-700 dark:bg-zinc-500/20 dark:text-zinc-300";
    default:
      return "bg-indigo-100 text-indigo-700 dark:bg-indigo-500/15 dark:text-indigo-300";
  }
}

export function statusTone(status: string): string {
  switch (status) {
    case "met":
      return "text-emerald-600 dark:text-emerald-400";
    case "not_met":
      return "text-rose-600 dark:text-rose-400";
    default:
      return "text-amber-600 dark:text-amber-400";
  }
}

export function confidenceTone(c: number): string {
  if (c >= 0.85) return "bg-emerald-500";
  if (c >= 0.7) return "bg-amber-500";
  return "bg-rose-500";
}

export function timeAgo(iso: string): string {
  const then = new Date(iso).getTime();
  const secs = Math.max(0, (Date.now() - then) / 1000);
  if (secs < 60) return `${Math.floor(secs)}s ago`;
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`;
  if (secs < 86400) return `${Math.floor(secs / 3600)}h ago`;
  return `${Math.floor(secs / 86400)}d ago`;
}

export function money(v: number): string {
  return `$${v.toFixed(3)}`;
}
