"use client";

import Link from "next/link";
import {
  Activity,
  CircleDollarSign,
  Clock,
  Gauge,
  ShieldCheck,
  Timer,
} from "lucide-react";
import { useCases } from "@/lib/useCases";
import { PageHeader } from "@/components/PageHeader";
import { NewCaseButton } from "@/components/NewCaseButton";
import { CaseList } from "@/components/CaseList";
import { EmptyState, Spinner, StatCard } from "@/components/ui";

export default function DashboardPage() {
  const { cases, loading } = useCases();

  const open = cases.filter((c) => !c.outcome);
  const approved = cases.filter((c) => c.outcome === "approved").length;
  const awaiting = cases.filter((c) => c.stage === "awaiting_approval").length;
  const managerQ = cases.filter((c) => c.needs_manager && !c.outcome).length;
  const decided = cases.filter((c) => c.outcome).length;
  const approvalRate = decided ? Math.round((approved / decided) * 100) : 0;
  const avgCost = cases.length
    ? cases.reduce((s, c) => s + c.est_cost_usd, 0) / cases.length
    : 0;

  return (
    <div>
      <PageHeader
        title="Prior-Authorization Autopilot"
        subtitle="Each case is assessed against the in-force coverage policy, every clinical claim is cited to a FHIR resource, and nothing reaches the payer without a human sign-off."
        action={<NewCaseButton />}
      />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 lg:gap-4 mb-6">
        <StatCard
          label="Open cases"
          value={open.length}
          hint={`${cases.length} total`}
          icon={<Activity className="w-5 h-5" />}
          accent="text-brand"
        />
        <StatCard
          label="Awaiting approval"
          value={awaiting}
          hint="needs a human decision"
          icon={<Clock className="w-5 h-5" />}
          accent="text-amber-500"
        />
        <StatCard
          label="Approval rate"
          value={`${approvalRate}%`}
          hint={`${approved}/${decided} decided`}
          icon={<Gauge className="w-5 h-5" />}
          accent="text-emerald-500"
        />
        <StatCard
          label="Avg agent cost"
          value={`$${avgCost.toFixed(3)}`}
          hint="per case"
          icon={<CircleDollarSign className="w-5 h-5" />}
          accent="text-violet-500"
        />
      </div>

      <div className="grid lg:grid-cols-3 gap-4 mb-6">
        <Link
          href="/cases?stage=awaiting_approval"
          className="card p-4 flex items-center gap-3 hover:shadow-soft transition"
        >
          <div className="grid place-items-center w-10 h-10 rounded-xl bg-amber-100 text-amber-600 dark:bg-amber-500/15">
            <Timer className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold">{awaiting} awaiting approval</div>
            <div className="text-xs text-muted">Review and sign off</div>
          </div>
        </Link>
        <Link
          href="/inbox"
          className="card p-4 flex items-center gap-3 hover:shadow-soft transition"
        >
          <div className="grid place-items-center w-10 h-10 rounded-xl bg-sky-100 text-sky-600 dark:bg-sky-500/15">
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold">
              {cases.filter((c) => c.stage === "awaiting_clinician").length} clinician gaps
            </div>
            <div className="text-xs text-muted">Chart could not confirm</div>
          </div>
        </Link>
        <Link
          href="/manager"
          className="card p-4 flex items-center gap-3 hover:shadow-soft transition"
        >
          <div className="grid place-items-center w-10 h-10 rounded-xl bg-violet-100 text-violet-600 dark:bg-violet-500/15">
            <ShieldCheck className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold">{managerQ} escalated</div>
            <div className="text-xs text-muted">Low confidence / cost / repeat denial</div>
          </div>
        </Link>
      </div>

      <h2 className="text-sm font-semibold text-muted uppercase tracking-wide mb-3">
        Recent cases
      </h2>
      {loading ? (
        <Spinner />
      ) : cases.length === 0 ? (
        <EmptyState
          title="No cases yet"
          body="Create a prior-auth case to watch the durable workflow assess the chart, draft a cited letter, and route it for approval."
          icon={<Activity className="w-8 h-8 mx-auto" />}
        />
      ) : (
        <CaseList cases={cases.slice(0, 8)} />
      )}
    </div>
  );
}
