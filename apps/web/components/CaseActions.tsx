"use client";

import { useState } from "react";
import { AlertTriangle, Check, ShieldAlert, X } from "lucide-react";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { CaseDetail } from "@/lib/types";
import { useSession } from "@/app/providers";

const APPROVER = new Set(["coordinator", "manager", "admin", "lead"]);
const MANAGER = new Set(["manager", "admin", "lead"]);
const CLINICIAN = new Set(["clinician", "manager", "admin", "lead"]);

export function CaseActions({
  detail,
  onDone,
}: {
  detail: CaseDetail;
  onDone: () => void;
}) {
  const { session } = useSession();
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const [err, setErr] = useState<string | null>(null);

  async function decide(decision: "approve" | "reject") {
    setBusy(true);
    setErr(null);
    try {
      await api.decide(session, detail.case_id, decision, note);
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  if (detail.stage === "awaiting_clinician") {
    return <ClinicianPanel detail={detail} onDone={onDone} />;
  }

  if (detail.stage !== "awaiting_approval") return null;

  const canRole = APPROVER.has(session.role);
  const needsManager = detail.needs_manager;
  const blocked = needsManager && !MANAGER.has(session.role);

  return (
    <div className="card p-5">
      <div className="flex items-center gap-2 mb-1">
        <ShieldAlert className="w-4 h-4 text-amber-500" />
        <h3 className="font-semibold">Human approval required</h3>
      </div>
      <p className="text-sm text-muted">
        Every submission needs a sign-off. The payer tool will not transmit without it.
      </p>

      {needsManager && (
        <div className="mt-3 flex items-start gap-2 rounded-lg bg-amber-50 dark:bg-amber-500/10 border border-amber-200 dark:border-amber-500/20 p-3 text-sm">
          <AlertTriangle className="w-4 h-4 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <span className="font-medium text-amber-800 dark:text-amber-300">
              Escalated to a manager
            </span>
            <span className="text-amber-700/80 dark:text-amber-300/80">
              {" "}
              — {detail.manager_reasons.map((r) => r.replace(/_/g, " ")).join(", ")}.
            </span>
          </div>
        </div>
      )}

      <textarea
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder="Optional note (captured as a labelled example if you override the agent)…"
        rows={2}
        className="mt-3 w-full text-sm rounded-lg border border-line bg-bg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand/40"
      />

      {err && <p className="mt-2 text-sm text-rose-600">{err}</p>}

      <div className="mt-3 flex gap-2">
        <button
          disabled={busy || blocked || !canRole}
          onClick={() => decide("approve")}
          className={clsx(
            "flex-1 inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold text-white transition",
            "bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed"
          )}
        >
          <Check className="w-4 h-4" /> Approve & submit
        </button>
        <button
          disabled={busy || blocked || !canRole}
          onClick={() => decide("reject")}
          className="inline-flex items-center justify-center gap-2 rounded-lg px-4 py-2.5 text-sm font-semibold transition border border-line hover:bg-bg disabled:opacity-40 disabled:cursor-not-allowed"
        >
          <X className="w-4 h-4" /> Reject
        </button>
      </div>
      {blocked && (
        <p className="mt-2 text-xs text-muted">
          Switch to the <span className="font-medium">manager</span> role to decide this case.
        </p>
      )}
      {!canRole && (
        <p className="mt-2 text-xs text-muted">Your role cannot approve submissions.</p>
      )}
    </div>
  );
}

function ClinicianPanel({ detail, onDone }: { detail: CaseDetail; onDone: () => void }) {
  const { session } = useSession();
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const allowed = CLINICIAN.has(session.role);
  const unknown = detail.decisions.filter((d) => d.status === "unknown");

  async function submit() {
    setBusy(true);
    setErr(null);
    try {
      await api.answerClinician(session, detail.case_id, answers);
      onDone();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Action failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card p-5">
      <h3 className="font-semibold">Clinician input needed</h3>
      <p className="text-sm text-muted">
        The chart could not confirm these criteria. Confirm or attach documentation.
      </p>
      <div className="mt-3 space-y-3">
        {unknown.map((d) => {
          const q =
            detail.clinician_questions.find((x) => x.includes(d.criterion_id)) ??
            detail.checklist.find((c) => c.id === d.criterion_id)?.text ??
            d.criterion_id;
          return (
            <div key={d.criterion_id}>
              <label className="text-sm font-medium">{q}</label>
              <input
                value={answers[d.criterion_id] ?? ""}
                onChange={(e) =>
                  setAnswers((a) => ({ ...a, [d.criterion_id]: e.target.value }))
                }
                placeholder="e.g. PT completed 6 weeks, note attached"
                className="mt-1 w-full text-sm rounded-lg border border-line bg-bg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-brand/40"
              />
            </div>
          );
        })}
      </div>
      {err && <p className="mt-2 text-sm text-rose-600">{err}</p>}
      <button
        disabled={busy || !allowed || Object.keys(answers).length === 0}
        onClick={submit}
        className="mt-4 w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40 disabled:cursor-not-allowed"
      >
        Submit answers
      </button>
      {!allowed && (
        <p className="mt-2 text-xs text-muted">Switch to the clinician role to answer.</p>
      )}
    </div>
  );
}
