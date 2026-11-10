"use client";

import { Inbox } from "lucide-react";
import { useCases } from "@/lib/useCases";
import { PageHeader } from "@/components/PageHeader";
import { CaseList } from "@/components/CaseList";
import { EmptyState, Spinner } from "@/components/ui";

export default function InboxPage() {
  const { cases, loading } = useCases({ stage: "awaiting_clinician" });

  return (
    <div>
      <PageHeader
        title="Clinician inbox"
        subtitle="Cases where the chart could not confirm a criterion. Your confirmation unblocks the draft — no chart digging required."
      />
      {loading ? (
        <Spinner />
      ) : cases.length === 0 ? (
        <EmptyState
          title="Inbox zero"
          body="No cases are waiting on clinical input right now."
          icon={<Inbox className="w-8 h-8 mx-auto" />}
        />
      ) : (
        <CaseList cases={cases} />
      )}
    </div>
  );
}
