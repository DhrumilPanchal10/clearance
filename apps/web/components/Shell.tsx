"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Activity,
  ClipboardList,
  Inbox,
  LayoutDashboard,
  ShieldCheck,
  Stethoscope,
} from "lucide-react";
import clsx from "clsx";
import { useSession } from "@/app/providers";
import type { Role } from "@/lib/types";

const NAV = [
  { href: "/", label: "Dashboard", icon: LayoutDashboard },
  { href: "/cases", label: "Case queue", icon: ClipboardList },
  { href: "/inbox", label: "Clinician inbox", icon: Inbox },
  { href: "/manager", label: "Manager & playbook", icon: ShieldCheck },
];

const ROLES: Role[] = ["coordinator", "clinician", "manager", "admin", "auditor"];

export function Shell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { session, setRole, ready } = useSession();

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[256px_1fr]">
      {/* Sidebar */}
      <aside className="hidden lg:flex flex-col border-r border-line bg-surface/80 backdrop-blur">
        <div className="flex items-center gap-2.5 px-5 h-16 border-b border-line">
          <div className="grid place-items-center w-9 h-9 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-600 text-white shadow-glow">
            <Activity className="w-5 h-5" />
          </div>
          <div>
            <div className="font-semibold tracking-tight leading-none">Clearance</div>
            <div className="text-[11px] text-muted mt-0.5">Prior-Auth Autopilot</div>
          </div>
        </div>
        <nav className="flex-1 p-3 space-y-1">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
            return (
              <Link
                key={href}
                href={href}
                className={clsx(
                  "flex items-center gap-3 px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                  active
                    ? "bg-brand-soft text-brand"
                    : "text-muted hover:text-ink hover:bg-bg"
                )}
              >
                <Icon className="w-[18px] h-[18px]" />
                {label}
              </Link>
            );
          })}
        </nav>
        <div className="p-4 border-t border-line text-[11px] text-muted leading-relaxed">
          <div className="flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse-dot" />
            Durable workflow engine
          </div>
          <div className="mt-1">Every clinical claim is FHIR-cited.</div>
        </div>
      </aside>

      {/* Main */}
      <div className="flex flex-col min-h-screen">
        <header className="sticky top-0 z-20 flex items-center justify-between h-16 px-5 lg:px-8 border-b border-line bg-surface/80 backdrop-blur">
          <div className="flex items-center gap-2 lg:hidden">
            <Activity className="w-5 h-5 text-brand" />
            <span className="font-semibold">Clearance</span>
          </div>
          <div className="hidden lg:block text-sm text-muted">
            {NAV.find((n) => (n.href === "/" ? pathname === "/" : pathname.startsWith(n.href)))
              ?.label ?? "Clearance"}
          </div>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-2">
              <Stethoscope className="w-4 h-4 text-muted" />
              <label className="sr-only" htmlFor="role">
                Active role
              </label>
              <select
                id="role"
                value={session.role}
                onChange={(e) => setRole(e.target.value as Role)}
                className="text-sm rounded-lg border border-line bg-card px-2.5 py-1.5 font-medium capitalize focus:outline-none focus:ring-2 focus:ring-brand/40"
              >
                {ROLES.map((r) => (
                  <option key={r} value={r} className="capitalize">
                    {r}
                  </option>
                ))}
              </select>
            </div>
            <div className="hidden sm:flex items-center gap-2 pl-3 border-l border-line">
              <div className="grid place-items-center w-8 h-8 rounded-full bg-brand-soft text-brand text-xs font-bold uppercase">
                {session.tenant.slice(-1)}
              </div>
              <div className="text-xs leading-tight">
                <div className="font-medium">{session.tenant}</div>
                <div className="text-muted">{ready ? "signed in (dev)" : "…"}</div>
              </div>
            </div>
          </div>
        </header>
        <main className="flex-1 px-5 lg:px-8 py-6 lg:py-8 max-w-[1200px] w-full mx-auto">
          {children}
        </main>
      </div>

      {/* Mobile nav */}
      <nav className="lg:hidden fixed bottom-0 inset-x-0 z-30 grid grid-cols-4 border-t border-line bg-surface/95 backdrop-blur">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={clsx(
                "flex flex-col items-center gap-0.5 py-2 text-[10px]",
                active ? "text-brand" : "text-muted"
              )}
            >
              <Icon className="w-5 h-5" />
              {label.split(" ")[0]}
            </Link>
          );
        })}
      </nav>
    </div>
  );
}
