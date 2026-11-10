"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";
import clsx from "clsx";
import Link from "next/link";
import { ClipboardList } from "lucide-react";
import { useCases } from "@/lib/useCases";
import { PageHeader } from "@/components/PageHeader";
import { NewCaseButton } from "@/components/NewCaseButton";
import { CaseList } from "@/components/CaseList";
import { EmptyState, Spinner } from "@/components/ui";

const FILTERS = [
  { key: "", label: "All" },
  { key: "awaiting_approval", label: "Awaiting approval" },
  { key: "awaiting_clinician", label: "Clinician gaps" },
  { key: "tracking", label: "With payer" },
  { key: "done", label: "Complete" },
];

function Queue() {
  const params = useSearchParams();
  const stage = params.get("stage") ?? "";
  const { cases, loading } = useCases(stage ? { stage } : {});

  return (
    <div>
      <PageHeader
        title="Case queue"
        subtitle="The coordinator's working queue across every stage of the pipeline."
        action={<NewCaseButton />}
      />

      <div className="flex flex-wrap gap-2 mb-5">
        {FILTERS.map((f) => (
          <Link
            key={f.key}
            href={f.key ? `/cases?stage=${f.key}` : "/cases"}
            className={clsx(
              "px-3 py-1.5 rounded-lg text-sm font-medium border transition",
              stage === f.key
                ? "bg-brand text-white border-brand"
                : "border-line text-muted hover:text-ink hover:bg-bg"
            )}
          >
            {f.label}
          </Link>
        ))}
      </div>

      {loading ? (
        <Spinner />
      ) : cases.length === 0 ? (
        <EmptyState
          title="Nothing here"
          body="No cases match this filter yet."
          icon={<ClipboardList className="w-8 h-8 mx-auto" />}
        />
      ) : (
        <CaseList cases={cases} />
      )}
    </div>
  );
}

export default function CasesPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <Queue />
    </Suspense>
  );
}
