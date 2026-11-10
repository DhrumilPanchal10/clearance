"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import type { CaseSummary } from "./types";
import { useSession } from "@/app/providers";

/** Polls the case list so queues reflect workflow progress without a refresh. */
export function useCases(query: Record<string, string> = {}, intervalMs = 2500) {
  const { session, ready } = useSession();
  const [cases, setCases] = useState<CaseSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const key = JSON.stringify(query);

  const refetch = useCallback(async () => {
    try {
      const res = await api.listCases(session, query);
      setCases(res.cases);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, key]);

  useEffect(() => {
    if (!ready) return;
    void refetch();
    const t = setInterval(refetch, intervalMs);
    return () => clearInterval(t);
  }, [ready, refetch, intervalMs]);

  return { cases, loading, error, refetch };
}
