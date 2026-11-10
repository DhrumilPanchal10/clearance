"use client";

import { useCallback, useEffect, useState } from "react";
import { api, subscribeCase } from "./api";
import type { CaseDetail } from "./types";
import { useSession } from "@/app/providers";

/**
 * Live case view: fetches the detail, then subscribes to live updates (SSE in
 * production, in-browser engine events on the static build) and re-reads on each
 * event so the timeline, criteria, and letter stay current as the case advances.
 */
export function useCase(id: string) {
  const { session, ready } = useSession();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setData(await api.getCase(session, id));
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load case");
    }
  }, [session, id]);

  useEffect(() => {
    if (!ready) return;
    void refetch();
    const unsub = subscribeCase(id, () => void refetch());
    return unsub;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, ready]);

  return { data, error, refetch };
}
