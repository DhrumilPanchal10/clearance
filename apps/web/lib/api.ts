"use client";

import type { CaseDetail, CaseSummary, PlaybookNote, Role } from "./types";

const BASE = "/api";

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

function headers(s: Session): HeadersInit {
  return {
    "Content-Type": "application/json",
    "X-Role": s.role,
    "X-Tenant": s.tenant,
    "X-User": s.user,
  };
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

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

export const api = {
  listCases: (s: Session, q: Record<string, string> = {}) => {
    const qs = new URLSearchParams(q).toString();
    return req<{ cases: CaseSummary[]; count: number }>(`/cases${qs ? `?${qs}` : ""}`, s);
  },
  getCase: (s: Session, id: string) => req<CaseDetail>(`/cases/${id}`, s),
  createCase: (
    s: Session,
    body: { patient_id: string; payer: string; procedure: string; as_of: string }
  ) => req<CaseDetail>(`/cases`, s, { method: "POST", body: JSON.stringify(body) }),
  decide: (s: Session, id: string, decision: "approve" | "reject", note = "") =>
    req<{ ok: boolean }>(`/cases/${id}/decision`, s, {
      method: "POST",
      body: JSON.stringify({ decision, note }),
    }),
  answerClinician: (s: Session, id: string, answers: Record<string, string>) =>
    req<{ ok: boolean }>(`/cases/${id}/clinician`, s, {
      method: "POST",
      body: JSON.stringify({ answers }),
    }),
  playbook: (s: Session) => req<{ notes: PlaybookNote[] }>(`/playbook`, s),
};

export function eventsUrl(id: string): string {
  return `${BASE}/cases/${id}/events`;
}
