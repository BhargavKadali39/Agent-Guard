"use client";

import { ShieldAlert, ShieldCheck, ShieldX } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";

import { Badge, type Tone } from "@/components/ui/badge";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { formatDuration, formatINR, formatTime, humanize, reasonText, shortId } from "@/lib/format";
import type { AuditEvent, Workflow, WorkflowState } from "@/lib/types";
import { cn, STATE_TONE } from "@/lib/utils";

export function StateBadge({ state }: { state: WorkflowState | string }) {
  const tone = (STATE_TONE as Record<string, Tone>)[state] ?? "neutral";
  return <Badge tone={tone}>{state.replace(/_/g, " ")}</Badge>;
}

export function ApprovalStatusBadge({ status }: { status: string }) {
  const tone: Tone =
    status === "approved" ? "success" : status === "pending" ? "warning" : status === "rejected" ? "critical" : "neutral";
  return <Badge tone={tone}>{status}</Badge>;
}

const CATEGORY_TONE: Record<string, Tone> = {
  workflow: "neutral",
  agent: "info",
  tool: "info",
  policy: "info",
  approval: "warning",
  execution: "success",
  security: "critical",
  evaluation: "warning",
  system: "neutral",
};

function AuthIcon({ outcome }: { outcome: string }) {
  if (outcome === "denied") return <ShieldX className="h-3.5 w-3.5 text-critical" aria-label="denied" />;
  if (outcome === "allowed") return <ShieldCheck className="h-3.5 w-3.5 text-success" aria-label="allowed" />;
  return null;
}

export function EventTimeline({ events, compact = false }: { events: AuditEvent[]; compact?: boolean }) {
  if (events.length === 0) return <p className="px-5 py-6 text-sm text-muted">No events recorded yet.</p>;
  return (
    <ol className="relative space-y-0">
      {events.map((event, index) => {
        const tone = CATEGORY_TONE[event.category] ?? "neutral";
        const severe = event.severity === "error" || event.authorization_outcome === "denied";
        return (
          <li key={event.id} className="relative flex gap-4 px-5 py-3">
            <div className="flex flex-col items-center">
              <span
                className={cn(
                  "mt-1 h-2.5 w-2.5 rounded-full border-2 border-surface",
                  severe ? "bg-critical" : event.severity === "warning" ? "bg-warning" : "bg-accent",
                )}
              />
              {index < events.length - 1 ? <span className="mt-1 w-px flex-1 bg-border" /> : null}
            </div>
            <div className="min-w-0 flex-1 pb-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-[11px] text-subtle">{formatTime(event.timestamp)}</span>
                <Badge tone={tone}>{event.category}</Badge>
                <span className="font-mono text-xs text-muted">{event.event_type}</span>
                <AuthIcon outcome={event.authorization_outcome} />
                {event.tool_name ? <span className="font-mono text-[11px] text-accent">{event.tool_name}</span> : null}
                {event.duration_ms !== null ? (
                  <span className="text-[11px] text-subtle">{formatDuration(event.duration_ms)}</span>
                ) : null}
                {event.workflow_state ? <span className="text-[11px] text-subtle">· {event.workflow_state}</span> : null}
              </div>
              <p className={cn("mt-1 text-sm", severe ? "text-foreground" : "text-muted")}>{event.message}</p>
              {!compact && event.payload && Object.keys(event.payload).length > 0 ? (
                <details className="mt-1">
                  <summary className="cursor-pointer text-[11px] text-subtle hover:text-muted">payload</summary>
                  <pre className="scrollbar-thin mt-1 max-h-56 overflow-auto rounded border border-border bg-background p-2 font-mono text-[11px] text-muted">
                    {JSON.stringify(event.payload, null, 2)}
                  </pre>
                </details>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function outcomeText(wf: Workflow): string {
  switch (wf.state) {
    case "COMPLETED":
      return wf.execution ? `refunded ${formatINR(wf.execution.amount_paise)} (simulated)` : "completed";
    case "REJECTED":
      return reasonText(wf.rejection_reason);
    case "FAILED":
      return `${wf.resumable ? "resumable · " : ""}${wf.failure_reason ?? "failed"}`;
    case "CANCELLED":
      return "cancelled";
    case "AWAITING_APPROVAL": {
      const pending = wf.approvals.find((a) => a.status === "pending");
      return pending ? `waiting for ${humanize(pending.required_role)} (${humanize(pending.reason)})` : "awaiting approval";
    }
    default:
      return wf.policy_decision ? `policy: ${wf.policy_decision.tier}` : "in progress";
  }
}

export function WorkflowTable({ workflows, emptyText = "No workflows yet." }: { workflows: Workflow[]; emptyText?: string }) {
  if (workflows.length === 0) return <p className="px-5 py-6 text-sm text-muted">{emptyText}</p>;
  return (
    <Table>
      <thead>
        <tr>
          <Th>Workflow</Th>
          <Th>Customer</Th>
          <Th>Order</Th>
          <Th>State</Th>
          <Th>Amount</Th>
          <Th>Outcome</Th>
          <Th>Created</Th>
        </tr>
      </thead>
      <tbody>
        {workflows.map((wf) => (
          <Tr key={wf.id}>
            <Td>
              <Link href={`/workflows/${wf.id}`} className="font-mono text-xs text-accent hover:underline">
                {shortId(wf.id)}
              </Link>
            </Td>
            <Td>
              <div className="max-w-[200px] truncate text-sm" title={wf.customer_name ?? wf.customer_id}>
                {wf.customer_name ?? wf.customer_id}
              </div>
              <div className="font-mono text-[11px] text-subtle">{wf.customer_id}</div>
            </Td>
            <Td className="whitespace-nowrap font-mono text-xs">{wf.order_id ?? "—"}</Td>
            <Td>
              <StateBadge state={wf.state} />
            </Td>
            <Td className="whitespace-nowrap font-mono text-xs">
              {wf.verification?.amount_paise != null ? formatINR(wf.verification.amount_paise) : "—"}
            </Td>
            <Td className="max-w-[280px] truncate text-xs text-muted" title={outcomeText(wf)}>
              {outcomeText(wf)}
            </Td>
            <Td className="whitespace-nowrap font-mono text-[11px] text-subtle">{formatTime(wf.created_at)}</Td>
          </Tr>
        ))}
      </tbody>
    </Table>
  );
}

export function Flag({ children, tone = "warning" }: { children: ReactNode; tone?: Tone }) {
  return (
    <Badge tone={tone} className="whitespace-normal break-all normal-case tracking-normal">
      <ShieldAlert className="h-3 w-3" />
      {children}
    </Badge>
  );
}
