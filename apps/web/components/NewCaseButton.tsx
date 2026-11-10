"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, X } from "lucide-react";
import { api } from "@/lib/api";
import { PROCEDURES } from "@/lib/ui";
import { useSession } from "@/app/providers";

export function NewCaseButton() {
  const { session } = useSession();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [form, setForm] = useState({
    patient_id: "",
    payer: "medicare",
    procedure: "lumbar_spine_mri",
    as_of: "2020-12-01",
  });

  async function create() {
    setBusy(true);
    setErr(null);
    try {
      const rec = await api.createCase(session, form);
      setOpen(false);
      router.push(`/case?id=${rec.case_id}`);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "Could not create case");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="inline-flex items-center gap-2 rounded-lg bg-brand px-3.5 py-2 text-sm font-semibold text-white shadow-soft hover:opacity-90"
      >
        <Plus className="w-4 h-4" /> New case
      </button>

      {open && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-sm p-4">
          <div className="card w-full max-w-md p-6 animate-fade-up">
            <div className="flex items-center justify-between">
              <h3 className="text-lg font-semibold">New prior-auth case</h3>
              <button onClick={() => setOpen(false)} className="text-muted hover:text-ink">
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="mt-4 space-y-3">
              <Field label="Patient ID (FHIR)">
                <input
                  value={form.patient_id}
                  onChange={(e) => setForm({ ...form, patient_id: e.target.value })}
                  placeholder="e.g. patient-00042"
                  className="input"
                />
              </Field>
              <div className="grid grid-cols-2 gap-3">
                <Field label="Payer">
                  <select
                    value={form.payer}
                    onChange={(e) => setForm({ ...form, payer: e.target.value })}
                    className="input"
                  >
                    <option value="medicare">Medicare</option>
                  </select>
                </Field>
                <Field label="As-of date">
                  <input
                    type="date"
                    value={form.as_of}
                    onChange={(e) => setForm({ ...form, as_of: e.target.value })}
                    className="input"
                  />
                </Field>
              </div>
              <Field label="Procedure">
                <select
                  value={form.procedure}
                  onChange={(e) => setForm({ ...form, procedure: e.target.value })}
                  className="input"
                >
                  {PROCEDURES.map((p) => (
                    <option key={p.value} value={p.value}>
                      {p.label}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {err && <p className="mt-3 text-sm text-rose-600">{err}</p>}
            <button
              disabled={busy || !form.patient_id}
              onClick={create}
              className="mt-5 w-full rounded-lg bg-brand px-4 py-2.5 text-sm font-semibold text-white hover:opacity-90 disabled:opacity-40"
            >
              {busy ? "Starting workflow…" : "Start assessment"}
            </button>
          </div>
        </div>
      )}
      <style jsx global>{`
        .input {
          width: 100%;
          border-radius: 0.5rem;
          border: 1px solid rgb(var(--line));
          background: rgb(var(--bg));
          padding: 0.55rem 0.7rem;
          font-size: 0.875rem;
        }
        .input:focus {
          outline: none;
          box-shadow: 0 0 0 2px rgb(var(--brand) / 0.4);
        }
      `}</style>
    </>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-xs font-medium text-muted">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}
