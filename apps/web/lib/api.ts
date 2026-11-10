"use client";

import type { CaseDetail, CaseSummary, PlaybookNote, Role } from "./types";
import { engine } from "./mockEngine";

const BASE = `${process.env.NEXT_PUBLIC_BASE_PATH ?? ""}/api`;
// Run the in-browser engine (no backend) when hosting statically (GitHub Pages)
// or on a backend-less host like Vercel (NEXT_PUBLIC_USE_ENGINE=1).
const STATIC =
  process.env.NEXT_PUBLIC_STATIC === "1" || process.env.NEXT_PUBLIC_USE_ENGINE === "1";

export interface Session {
  role: Role;
  tenant: string;
  user: string;
}

const DEFAULT_SESSION: Session = { role: "coordinator", tenant: "clinic-a", user: "demo" };

export function loadSession(): Session {
  if (typeof window === "undefined") return DEFAULT_SESSION;
  try {
    const raw = window.localStorage.getItem("clearance.session");
    if (raw) return { ...DEFAULT_SESSION, ...JSON.parse(raw) };
  } catch {
    /* ignore */
  }
  return DEFAULT_SESSION;
}

export function saveSession(s: Session): void {
  try {
    window.localStorage.setItem("clearance.session", JSON.stringify(s));
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

function headers(s: Session): HeadersInit {
  return { "Content-Type": "application/json", "X-Role": s.role, "X-Tenant": s.tenant, "X-User": s.user };
}

async function req<T>(path: string, s: Session, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { ...headers(s), ...(init?.headers || {}) },
    cache: "no-store",
  });
  if (!res.ok) {
    let detail = res.statusText;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(res.status, detail);
  }
  return res.json() as Promise<T>;
}

function newId(): string {
  try {
    return `case-${crypto.randomUUID().replace(/-/g, "").slice(0, 12)}`;
  } catch {
    return `case-${Math.random().toString(36).slice(2, 14)}`;
  }
}

// --- in-browser (static) implementation ------------------------------------ //

function mockList(s: Session, q: Record<string, string>): { cases: CaseSummary[]; count: number } {
  let rows = engine().list(s.tenant, s.role === "admin");
  if (q.stage) rows = rows.filter((r) => r.stage === q.stage);
  if (q.needs_manager != null) rows = rows.filter((r) => String(r.needs_manager) === q.needs_manager);
  if (q.mine_role === "manager") rows = rows.filter((r) => r.needs_manager);
  if (q.mine_role === "clinician") rows = rows.filter((r) => r.stage === "awaiting_clinician");
  return { cases: rows, count: rows.length };
}

function scoped(rec: CaseDetail | null, s: Session): CaseDetail {
  if (!rec || (s.role !== "admin" && rec.tenant_id !== s.tenant)) {
    throw new ApiError(404, "case not found");
  }
  return rec;
}

export const api = {
  listCases: (s: Session, q: Record<string, string> = {}) => {
    if (STATIC) return Promise.resolve(mockList(s, q));
    const qs = new URLSearchParams(q).toString();
    return req<{ cases: CaseSummary[]; count: number }>(`/cases${qs ? `?${qs}` : ""}`, s);
  },
  getCase: (s: Session, id: string) => {
    if (STATIC) return Promise.resolve(scoped(engine().get(id), s));
    return req<CaseDetail>(`/cases/${id}`, s);
  },
  createCase: (s: Session, body: { patient_id: string; payer: string; procedure: string; as_of: string }) => {
    if (STATIC) {
      return engine().createCase({ case_id: newId(), tenant_id: s.tenant, ...body });
    }
    return req<CaseDetail>(`/cases`, s, { method: "POST", body: JSON.stringify(body) });
  },
  decide: (s: Session, id: string, decision: "approve" | "reject", note = "") => {
    if (STATIC) {
      engine().decide(id, decision, s.role);
      return Promise.resolve({ ok: true });
    }
    return req<{ ok: boolean }>(`/cases/${id}/decision`, s, { method: "POST", body: JSON.stringify({ decision, note }) });
  },
  answerClinician: (s: Session, id: string, answers: Record<string, string>) => {
    if (STATIC) {
      engine().answerClinician(id, answers);
      return Promise.resolve({ ok: true });
    }
    return req<{ ok: boolean }>(`/cases/${id}/clinician`, s, { method: "POST", body: JSON.stringify({ answers }) });
  },
  playbook: (s: Session) => {
    if (STATIC) return Promise.resolve({ notes: engine().playbook() });
    return req<{ notes: PlaybookNote[] }>(`/playbook`, s);
  },
};

/** Subscribe to a case's live updates (SSE in prod; engine events when static). */
export function subscribeCase(id: string, onChange: () => void): () => void {
  if (STATIC) return engine().subscribeCase(id, onChange);
  const es = new EventSource(`${BASE}/cases/${id}/events`);
  const handler = () => onChange();
  for (const name of ["stage", "decision", "human", "payer", "error"]) {
    es.addEventListener(name, handler as EventListener);
  }
  es.addEventListener("end", () => es.close());
  es.onerror = () => es.close();
  return () => es.close();
}
