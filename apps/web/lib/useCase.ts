"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, eventsUrl } from "./api";
import type { CaseDetail, TimelineEvent } from "./types";
import { useSession } from "@/app/providers";

/**
 * Live case view: fetches the detail, then subscribes to the SSE stream and
 * re-fetches on every event so the timeline, criteria, and letter stay current
 * as the durable workflow advances.
 */
export function useCase(id: string) {
  const { session, ready } = useSession();
  const [data, setData] = useState<CaseDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [live, setLive] = useState<TimelineEvent[]>([]);
  const esRef = useRef<EventSource | null>(null);

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
    const es = new EventSource(eventsUrl(id));
    esRef.current = es;
    const onEvent = (ev: MessageEvent) => {
      try {
        const parsed = JSON.parse(ev.data) as TimelineEvent;
        setLive((prev) => (prev.some((p) => p.seq === parsed.seq) ? prev : [...prev, parsed]));
      } catch {
        /* keep-alive frame */
      }
      void refetch();
    };
    for (const name of ["stage", "decision", "human", "payer", "error"]) {
      es.addEventListener(name, onEvent as EventListener);
    }
    es.addEventListener("end", () => es.close());
    es.onerror = () => es.close();
    return () => es.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, ready]);

  return { data, error, live, refetch };
}
