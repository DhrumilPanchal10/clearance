"use client";

/**
 * In-browser orchestration engine (GitHub Pages / static build).
 *
 * GitHub Pages serves static files only — there is no FastAPI backend to talk
 * to — so this is a faithful TypeScript port of `clearance.api.demo`: it loads
 * the real ground-truth checklists and drives each case through the same state
 * machine (assess → clinician gap-fill → draft → approval → submit → track →
 * appeal) with deterministic, synthesized outcomes. The whole product is then
 * fully clickable with zero infrastructure.
 */

import type {
  CaseDetail,
  CaseSummary,
  Criterion,
  Decision,
  PlaybookNote,
  Stage,
  TimelineEvent,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const PROCEDURES = ["lumbar_spine_mri", "knee_mri", "ct_abdomen"];
const VERSIONS: Record<string, string> = {
  lumbar_spine_mri: "L34220",
  knee_mri: "NCD-220.2",
  ct_abdomen: "L34415",
};
const COST_PER_AGENT_DECISION = 0.012;
const LOW_CONFIDENCE = 0.75;
const HIGH_COST = 0.08;
const MAX_APPEALS = 2;
const STEP_MS = 650; // pacing so the live timeline animates

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

const now = () => new Date().toISOString();
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface Record_ extends CaseDetail {
  _attempt: number;
  as_of: string;
}

type Listener = () => void;

interface Episode {
  payer: string;
  procedure: string;
  outcome: string;
  denial_reason: string | null;
  policy_version: string | null;
}

const checklistCache = new Map<string, Criterion[]>();

async function loadChecklist(procedure: string): Promise<Criterion[]> {
  if (checklistCache.has(procedure)) return checklistCache.get(procedure)!;
  try {
    const res = await fetch(`${BASE}/checklists/${procedure}.json`, { cache: "force-cache" });
    const data = await res.json();
    const criteria: Criterion[] = (data.criteria ?? []).map((c: any) => ({
      id: c.id,
      text: c.text,
      kind: c.kind,
      rule_spec: c.rule_spec,
    }));
    checklistCache.set(procedure, criteria);
    return criteria;
  } catch {
    return [];
  }
}

function fhirType(c: Criterion): string {
  const t = (c.text || "").toLowerCase();
  if (t.includes("age")) return "Patient";
  if (t.includes("therapy") || t.includes("conservative")) return "Procedure";
  if (t.includes("pregnan")) return "Observation";
  return "Condition";
}

class Engine {
  private cases = new Map<string, Record_>();
  private events = new Map<string, TimelineEvent[]>();
  private seq = new Map<string, number>();
  private gates = new Map<string, { clinician?: (a: any) => void; coordinator?: (d: string) => void }>();
  private episodes: Episode[] = [];
  private caseListeners = new Map<string, Set<Listener>>();
  private listListeners = new Set<Listener>();
  private seeded = false;

  // --- subscriptions --------------------------------------------------- //

  subscribeCase(id: string, cb: Listener): () => void {
    const set = this.caseListeners.get(id) ?? new Set();
    set.add(cb);
    this.caseListeners.set(id, set);
    return () => set.delete(cb);
  }

  subscribeList(cb: Listener): () => void {
    this.listListeners.add(cb);
    return () => this.listListeners.delete(cb);
  }

  private notify(id: string) {
    this.caseListeners.get(id)?.forEach((cb) => cb());
    this.listListeners.forEach((cb) => cb());
  }

  private emit(id: string, stage: Stage, kind: TimelineEvent["kind"], message: string, data: Record<string, unknown> = {}) {
    const n = (this.seq.get(id) ?? 0) + 1;
    this.seq.set(id, n);
    const ev: TimelineEvent = { seq: n, at: now(), stage, kind, message, data };
    const log = this.events.get(id) ?? [];
    log.push(ev);
    this.events.set(id, log);
    this.notify(id);
  }

  private setStage(rec: Record_, stage: Stage, message: string, data: Record<string, unknown> = {}) {
    rec.stage = stage;
    rec.updated_at = now();
    this.emit(rec.case_id, stage, "stage", message, data);
  }

  // --- reads ----------------------------------------------------------- //

  list(tenant: string, admin = false): CaseSummary[] {
    return [...this.cases.values()]
      .filter((r) => admin || r.tenant_id === tenant)
      .sort((a, b) => (a.created_at < b.created_at ? 1 : -1))
      .map(toSummary);
  }

  get(id: string): CaseDetail | null {
    const rec = this.cases.get(id);
    if (!rec) return null;
    return { ...rec, timeline: [...(this.events.get(id) ?? [])] };
  }

  playbook(): PlaybookNote[] {
    const groups = new Map<string, Episode[]>();
    for (const e of this.episodes) {
      const k = `${e.payer}:${e.procedure}`;
      groups.set(k, [...(groups.get(k) ?? []), e]);
    }
    const notes: PlaybookNote[] = [];
    for (const eps of groups.values()) {
      if (eps.length < 3) continue;
      const latest = eps[eps.length - 1].policy_version;
      const cohort = eps.filter((e) => e.policy_version === latest);
      const approvals = cohort.filter((e) => e.outcome === "approved").length;
      const denials = cohort.filter((e) => e.outcome === "denied").length;
      const counts = new Map<string, number>();
      cohort.filter((e) => e.denial_reason).forEach((e) => counts.set(e.denial_reason!, (counts.get(e.denial_reason!) ?? 0) + 1));
      const top = [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 3) as [string, number][];
      const total = approvals + denials;
      const rate = total ? approvals / total : 0;
      const guidance = top.length
        ? `${approvals}/${total} approved (${Math.round(rate * 100)}%). Most common denial: '${top[0][0].replace(/_/g, " ")}' (${top[0][1]}×) — ensure that criterion is fully evidenced and cited before submitting.`
        : `${approvals}/${total} approved (${Math.round(rate * 100)}%).`;
      notes.push({ payer: eps[0].payer, procedure: eps[0].procedure, policy_version: latest, approvals, denials, top_denial_reasons: top, guidance });
    }
    return notes;
  }

  // --- human inputs ---------------------------------------------------- //

  decide(id: string, decision: string, role: string) {
    this.gates.get(id)?.coordinator?.(decision);
    this.emit(id, "awaiting_approval", "human", `${role} ${decision}`);
  }

  answerClinician(id: string, answers: Record<string, string>) {
    this.gates.get(id)?.clinician?.(answers);
    this.emit(id, "awaiting_clinician", "human", "Clinician answered gaps");
  }

  // --- lifecycle ------------------------------------------------------- //

  async createCase(payload: { case_id: string; tenant_id: string; patient_id: string; payer: string; procedure: string; as_of: string }): Promise<CaseDetail> {
    const rec: Record_ = {
      case_id: payload.case_id,
      tenant_id: payload.tenant_id,
      patient_id: payload.patient_id,
      payer: payload.payer,
      procedure: payload.procedure,
      as_of: payload.as_of,
      stage: "created",
      outcome: null,
      verdict: null,
      appeal_cycles: 0,
      reminders: 0,
      confidence: 1,
      est_cost_usd: 0,
      needs_manager: false,
      assigned_role: "coordinator",
      criteria_total: 0,
      criteria_met: 0,
      policy_version: null,
      denial_reason: null,
      claim_id: null,
      manager_reasons: [],
      checklist: [],
      decisions: [],
      evidence_cards: [],
      letter: null,
      packet: null,
      clinician_questions: [],
      errors: [],
      created_at: now(),
      updated_at: now(),
      _attempt: 0,
      timeline: [],
    };
    this.cases.set(rec.case_id, rec);
    this.gates.set(rec.case_id, {});
    this.emit(rec.case_id, "created", "stage", "Case created");
    void this.drive(rec.case_id);
    return this.get(rec.case_id)!;
  }

  private waitCoordinator(id: string): Promise<string> {
    return new Promise((resolve) => {
      this.gates.get(id)!.coordinator = resolve;
    });
  }
  private waitClinician(id: string): Promise<Record<string, string>> {
    return new Promise((resolve) => {
      this.gates.get(id)!.clinician = resolve;
    });
  }

  private async drive(id: string) {
    const rec = this.cases.get(id)!;
    await this.assess(rec);
    for (;;) {
      await this.draft(rec);
      if (!(await this.approvalGate(rec))) return;
      let status = await this.submit(rec);
      status = await this.track(rec, status);
      if (status === "approved") return this.finish(rec, "approved");
      if (rec.appeal_cycles >= MAX_APPEALS) return this.finish(rec, "denied");
      await this.appeal(rec);
      rec.appeal_cycles += 1;
    }
  }

  private async assess(rec: Record_) {
    this.setStage(rec, "assessing", "Assessing chart against policy criteria");
    await sleep(STEP_MS);
    const checklist = await loadChecklist(rec.procedure);
    const seed = hash(rec.patient_id + rec.procedure);
    const decisions: Decision[] = [];
    checklist.forEach((c, i) => {
      const isRule = c.kind === "rule";
      const unknown = !isRule && (seed >> (i + 1)) % 5 === 0;
      const status = unknown ? "unknown" : "met";
      const conf = isRule ? 1 : (seed >> i) % 4 === 0 ? 0.68 : 0.93;
      const ref = `${fhirType(c)}/${((seed >> (i * 2)) % 9000) + 1000}`;
      decisions.push({
        criterion_id: c.id,
        status: status as Decision["status"],
        evidence_refs: unknown ? [] : [ref],
        confidence: conf,
        method: isRule ? "rule" : "agent",
        rationale: isRule ? "" : unknown ? "Not determinable from structured chart data; clinician confirmation requested." : "Chart notes support this criterion; cited to the referenced resource.",
      });
    });
    rec.policy_version = VERSIONS[rec.procedure] ?? null;
    rec.checklist = checklist;
    rec.decisions = decisions;
    rec.evidence_cards = checklist.map((c, i) => ({
      criterion_id: c.id,
      summary: decisions[i].status === "unknown" ? "No structured evidence found in the chart for this criterion." : `Documented in the patient chart: ${c.text}.`,
      fhir_refs: decisions[i].evidence_refs,
    }));
    const agentCount = decisions.filter((d) => d.method === "agent").length;
    rec.est_cost_usd = Math.round(agentCount * COST_PER_AGENT_DECISION * 10000) / 10000;
    this.emit(rec.case_id, "assessing", "decision", "Criteria evaluated", {
      met: decisions.filter((d) => d.status === "met").length,
      total: decisions.length,
    });

    const unknowns = decisions.filter((d) => d.status === "unknown");
    if (unknowns.length) {
      rec.clinician_questions = unknowns.map((d) => {
        const text = checklist.find((c) => c.id === d.criterion_id)?.text ?? d.criterion_id;
        return `Unable to confirm from the chart: ${text}. Can you confirm or provide documentation?`;
      });
      this.setStage(rec, "awaiting_clinician", "Gaps need a clinician's input", { questions: rec.clinician_questions });
      const answers = await this.waitClinician(rec.case_id);
      for (const d of rec.decisions) {
        if (d.status === "unknown" && answers[d.criterion_id]) {
          d.status = "met";
          d.method = "agent";
          d.rationale = "Provided by clinician";
        }
      }
    }
  }

  private async draft(rec: Record_) {
    this.setStage(rec, "drafting", "Drafting cited medical-necessity letter");
    await sleep(STEP_MS);
    const byId = new Map(rec.checklist.map((c) => [c.id, c]));
    const lines = rec.decisions
      .filter((d) => d.status === "met")
      .map((d) => ({ text: `The patient meets the criterion: ${byId.get(d.criterion_id)?.text ?? d.criterion_id}.`, fhir_refs: d.evidence_refs }));
    rec.verdict = "pass";
    rec.letter = { title: `Letter of Medical Necessity — ${rec.procedure}`, sections: [{ heading: "Clinical justification", lines }] };
    this.emit(rec.case_id, "drafting", "decision", "Verifier verdict: pass", { verdict: "pass" });
  }

  private route(rec: Record_) {
    const reasons: string[] = [];
    const agentConf = rec.decisions.filter((d) => d.method === "agent").map((d) => d.confidence);
    const minConf = agentConf.length ? Math.min(...agentConf) : 1;
    if (minConf < LOW_CONFIDENCE) reasons.push("low_confidence");
    if (rec.est_cost_usd > HIGH_COST) reasons.push("high_cost");
    if (rec.appeal_cycles >= 1) reasons.push("repeat_denial");
    return reasons;
  }

  private async approvalGate(rec: Record_): Promise<boolean> {
    const reasons = this.route(rec);
    rec.manager_reasons = reasons;
    rec.needs_manager = reasons.length > 0;
    rec.assigned_role = rec.needs_manager ? "manager" : "coordinator";
    this.setStage(rec, "awaiting_approval", `Awaiting ${rec.assigned_role} approval`, { assigned_role: rec.assigned_role, reasons });
    const decision = await this.waitCoordinator(rec.case_id);
    this.gates.get(rec.case_id)!.coordinator = undefined;
    if (decision === "reject") {
      this.finish(rec, "rejected");
      return false;
    }
    return true;
  }

  private async submit(rec: Record_): Promise<string> {
    rec._attempt += 1;
    this.setStage(rec, "submitting", `Submitting to payer (attempt ${rec._attempt})`);
    await sleep(STEP_MS);
    const seed = hash(rec.case_id);
    const bucket = seed % 10;
    let status: string;
    if (bucket < 6 || rec._attempt >= 2) status = "approved";
    else if (bucket < 8) status = "pended";
    else {
      status = "denied";
      rec.denial_reason = "insufficient_documentation";
    }
    rec.claim_id = `PA-${seed % 100000}`;
    return status;
  }

  private async track(rec: Record_, status: string): Promise<string> {
    this.setStage(rec, "tracking", "Tracking payer decision", { status });
    while (status === "pended" || status === "more_info") {
      await sleep(STEP_MS * 3); // simulated payer dwell, then it resolves
      status = "approved";
      this.emit(rec.case_id, "tracking", "payer", "Payer update: approved", { status });
    }
    return status;
  }

  private async appeal(rec: Record_) {
    this.setStage(rec, "appealing", `Denied (${rec.denial_reason}); drafting appeal`, { denial_reason: rec.denial_reason });
    await sleep(STEP_MS);
    rec.packet = { ...(rec.packet ?? {}), appeal: { kind: "appeal" } };
  }

  private finish(rec: Record_, outcome: string) {
    rec.outcome = outcome as CaseDetail["outcome"];
    this.setStage(rec, "done", `Case ${outcome}`, { outcome });
    if (outcome === "approved" || outcome === "denied") {
      this.episodes.push({ payer: rec.payer, procedure: rec.procedure, outcome, denial_reason: outcome === "denied" ? rec.denial_reason : null, policy_version: rec.policy_version });
    }
  }

  async seed() {
    if (this.seeded) return;
    this.seeded = true;
    const seeds: [string, string][] = [
      ["patient-00017", "lumbar_spine_mri"],
      ["patient-00042", "knee_mri"],
      ["patient-00088", "ct_abdomen"],
      ["patient-00103", "lumbar_spine_mri"],
      ["patient-00129", "knee_mri"],
      ["patient-00155", "ct_abdomen"],
      ["patient-00204", "lumbar_spine_mri"],
    ];
    // Seed a little playbook history so the manager view has content.
    for (const p of PROCEDURES) {
      this.episodes.push(
        { payer: "medicare", procedure: p, outcome: "approved", denial_reason: null, policy_version: VERSIONS[p] },
        { payer: "medicare", procedure: p, outcome: "approved", denial_reason: null, policy_version: VERSIONS[p] },
        { payer: "medicare", procedure: p, outcome: "denied", denial_reason: "insufficient_documentation", policy_version: VERSIONS[p] },
      );
    }
    for (let i = 0; i < seeds.length; i++) {
      await this.createCase({
        case_id: `demo-${String(i).padStart(2, "0")}-${seeds[i][0].slice(-5)}`,
        tenant_id: "clinic-a",
        patient_id: seeds[i][0],
        payer: "medicare",
        procedure: seeds[i][1],
        as_of: "2020-12-01",
      });
    }
  }
}

function toSummary(r: Record_): CaseSummary {
  return {
    case_id: r.case_id,
    tenant_id: r.tenant_id,
    patient_id: r.patient_id,
    payer: r.payer,
    procedure: r.procedure,
    stage: r.stage,
    outcome: r.outcome,
    verdict: r.verdict,
    confidence: r.confidence,
    est_cost_usd: r.est_cost_usd,
    needs_manager: r.needs_manager,
    assigned_role: r.assigned_role,
    criteria_total: r.decisions.length,
    criteria_met: r.decisions.filter((d) => d.status === "met").length,
    appeal_cycles: r.appeal_cycles,
    updated_at: r.updated_at,
    created_at: r.created_at,
  };
}

let _engine: Engine | null = null;
export function engine(): Engine {
  if (!_engine) {
    _engine = new Engine();
    void _engine.seed();
  }
  return _engine;
}
