"use client";

import { ShieldAlert } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { EmptyState, ErrorBanner, PageHeader } from "@/components/ui/misc";
import { EventTimeline } from "@/components/workflow-bits";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";
import { humanize } from "@/lib/format";

const LABELS: Record<string, string> = {
  "security.injection_suspected": "Injection attempts flagged",
  "tool.authorization_denied": "Tool calls denied",
  "tool.unknown_requested": "Unknown tools requested",
  "approval.decision_denied": "Approval decisions denied",
  "approval.invalidated": "Approvals invalidated",
  "workflow.invalid_transition_blocked": "Illegal transitions blocked",
};

export default function SecurityPage() {
  const { data, error, refresh } = useQuery(() => Promise.all([api.securitySummary(), api.securityEvents(150)]), []);
  const summary = data?.[0] ?? null;
  const events = data?.[1].items ?? [];

  return (
    <AppShell>
      <PageHeader
        title="Security Monitor"
        description="Denied operations, policy violations and suspicious content. Every entry here was enforced by backend code, not by a prompt."
        actions={
          <Button variant="secondary" size="sm" onClick={refresh}>
            Refresh
          </Button>
        }
      />
      <ErrorBanner message={error} />
      {summary ? (
        <div className="mb-6 grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
          {Object.entries(summary.counts).map(([key, count]) => (
            <Card key={key} className="px-4 py-3">
              <div className="text-[11px] font-medium uppercase tracking-wide text-subtle">{LABELS[key] ?? humanize(key)}</div>
              <div className={`mt-1 font-mono text-2xl font-semibold ${count > 0 ? "text-critical" : "text-foreground"}`}>{count}</div>
            </Card>
          ))}
        </div>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Security events" description={`${events.length} most recent (newest first)`} />
          {events.length === 0 ? <EmptyState title="No security events" description="Run the prompt-injection example in the playground to generate some." /> : <EventTimeline events={events} />}
        </Card>
        <Card>
          <CardHeader title="Denied tools" description="Which tools the agent (or a user) tried to call without authorization" />
          <CardBody>
            {summary && Object.keys(summary.denied_tools).length ? (
              <ul className="space-y-2">
                {Object.entries(summary.denied_tools)
                  .sort((a, b) => b[1] - a[1])
                  .map(([tool, count]) => (
                    <li key={tool} className="flex items-center justify-between rounded-md border border-border bg-background px-3 py-2 text-sm">
                      <span className="flex items-center gap-2 font-mono text-xs">
                        <ShieldAlert className="h-3.5 w-3.5 text-critical" /> {tool}
                      </span>
                      <span className="font-mono text-xs text-muted">{count}</span>
                    </li>
                  ))}
              </ul>
            ) : (
              <p className="text-sm text-muted">No denied tool calls recorded.</p>
            )}
            <p className="mt-4 text-xs text-subtle">
              Total denied actions (all kinds): <span className="font-mono text-foreground">{summary?.total_denied ?? 0}</span>
            </p>
          </CardBody>
        </Card>
      </div>
    </AppShell>
  );
}
