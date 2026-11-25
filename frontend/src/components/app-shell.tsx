"use client";

import {
  Activity,
  BookOpenCheck,
  Boxes,
  CheckSquare,
  FlaskConical,
  LayoutDashboard,
  LogOut,
  MessageSquareText,
  ScrollText,
  ShieldAlert,
  Workflow,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { useAuth, useRequireAuth } from "@/lib/auth";
import { roleLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Spinner } from "./ui/misc";

const NAV = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/playground", label: "Agent Playground", icon: MessageSquareText },
  { href: "/workflows", label: "Workflow Explorer", icon: Workflow },
  { href: "/approvals", label: "Approval Center", icon: CheckSquare },
  { href: "/security", label: "Security Monitor", icon: ShieldAlert, permission: "security:read" },
  { href: "/failure-lab", label: "Failure Lab", icon: FlaskConical },
  { href: "/audit", label: "Audit Timeline", icon: ScrollText },
  { href: "/architecture", label: "Architecture", icon: Boxes },
] as const;

export function AppShell({ children }: { children: ReactNode }) {
  const authed = useRequireAuth();
  const { user, logout, can } = useAuth();
  const pathname = usePathname();

  if (!authed || !user) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Spinner className="h-6 w-6" />
      </div>
    );
  }

  return (
    <div className="flex min-h-screen">
      <aside className="sticky top-0 flex h-screen w-60 shrink-0 flex-col border-r border-border bg-surface">
        <div className="flex items-center gap-3 border-b border-border px-5 py-4">
          <div className="flex h-9 w-9 items-center justify-center rounded-md bg-accent-soft text-accent">
            <Activity className="h-5 w-5" />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold tracking-tight">AgentGuard</div>
            <div className="text-[11px] text-subtle">The GenAI Foundry</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3 py-3">
          {NAV.filter((item) => !("permission" in item) || can(item.permission)).map((item) => {
            const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
            const Icon = item.icon;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 rounded-md px-3 py-2 text-sm transition-colors",
                  active ? "bg-accent-soft text-accent" : "text-muted hover:bg-surface-raised hover:text-foreground",
                )}
              >
                <Icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
        <div className="border-t border-border px-4 py-3">
          <div className="mb-2 rounded-md border border-warning/30 bg-warning/10 px-2.5 py-1.5 text-[11px] text-warning">
            <BookOpenCheck className="mr-1 inline h-3 w-3" />
            Simulation only · no real money, no real customers
          </div>
          <div className="flex items-center justify-between gap-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{user.display_name}</div>
              <div className="truncate text-[11px] text-subtle">{roleLabel(user.role)}</div>
            </div>
            <button
              type="button"
              onClick={logout}
              className="rounded-md p-2 text-muted hover:bg-surface-raised hover:text-foreground"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      </aside>
      <main className="min-w-0 flex-1 px-8 py-6">{children}</main>
    </div>
  );
}
