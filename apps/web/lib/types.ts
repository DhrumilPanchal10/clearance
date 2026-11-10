export type Stage =
  | "created"
  | "assessing"
  | "awaiting_clinician"
  | "drafting"
  | "awaiting_approval"
  | "submitting"
  | "tracking"
  | "appealing"
  | "done"
  | "error";

export type Outcome = "approved" | "denied" | "rejected" | null;
export type Role = "coordinator" | "clinician" | "manager" | "admin" | "auditor";

export interface CaseSummary {
  case_id: string;
  tenant_id: string;
  patient_id: string;
  payer: string;
  procedure: string;
  stage: Stage;
  outcome: Outcome;
  verdict: string | null;
  confidence: number;
  est_cost_usd: number;
  needs_manager: boolean;
  assigned_role: string;
  criteria_total: number;
  criteria_met: number;
  appeal_cycles: number;
  updated_at: string;
  created_at: string;
}

export interface Decision {
  criterion_id: string;
  status: "met" | "not_met" | "unknown";
  evidence_refs: string[];
  confidence: number;
  method: "rule" | "agent";
  rationale: string;
}

export interface Criterion {
  id: string;
  text: string;
  kind?: string;
}

export interface EvidenceCard {
  criterion_id: string;
  summary: string;
  fhir_refs: string[];
}

export interface TimelineEvent {
  seq: number;
  at: string;
  stage: Stage;
  kind: "stage" | "decision" | "human" | "payer" | "error";
  message: string;
  data: Record<string, unknown>;
}

export interface CaseDetail extends CaseSummary {
  policy_version: string | null;
  denial_reason: string | null;
  claim_id: string | null;
  manager_reasons: string[];
  reminders: number;
  checklist: Criterion[];
  decisions: Decision[];
  evidence_cards: EvidenceCard[];
  letter: { title?: string; sections?: LetterSection[] } | null;
  packet: Record<string, unknown> | null;
  clinician_questions: string[];
  errors: string[];
  timeline: TimelineEvent[];
}

export interface LetterSection {
  heading: string;
  lines: { text: string; fhir_refs?: string[] }[];
}

export interface PlaybookNote {
  payer: string;
  procedure: string;
  policy_version: string | null;
  approvals: number;
  denials: number;
  top_denial_reasons: [string, number][];
  guidance: string;
}
