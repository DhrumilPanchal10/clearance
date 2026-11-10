"use client";

import { createContext, useContext, useEffect, useState } from "react";
import { loadSession, saveSession, type Session } from "@/lib/api";
import type { Role } from "@/lib/types";

interface SessionCtx {
  session: Session;
  setRole: (role: Role) => void;
  setTenant: (tenant: string) => void;
  ready: boolean;
}

const Ctx = createContext<SessionCtx | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<Session>({
    role: "coordinator",
    tenant: "clinic-a",
    user: "demo",
  });
  const [ready, setReady] = useState(false);

  useEffect(() => {
    setSession(loadSession());
    setReady(true);
  }, []);

  const update = (next: Session) => {
    setSession(next);
    saveSession(next);
  };

  return (
    <Ctx.Provider
      value={{
        session,
        ready,
        setRole: (role) => update({ ...session, role }),
        setTenant: (tenant) => update({ ...session, tenant }),
      }}
    >
      {children}
    </Ctx.Provider>
  );
}

export function useSession(): SessionCtx {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useSession must be used within SessionProvider");
  return ctx;
}
