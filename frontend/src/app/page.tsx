"use client";

import { ArrowRight, RefreshCw } from "lucide-react";
import Link from "next/link";

import { AppShell } from "@/components/app-shell";
import { StateDistributionChart, WorkflowsPerDayChart } from "@/components/charts";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner, PageHeader, Spinner } from "@/components/ui/misc";
import { WorkflowTable } from "@/components/workflow-bits";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";
import { formatDuration, formatINR } from "@/lib/format";

function MetricCard({ label, value, hint, tone }: { label: string; value: string | number; hint?: string; tone?: "success" | "warning" | "critical" | "accent" }) {
  const color =
    tone === "success" ? "text-success" : tone === "warning" ? "text-warning" : tone === "critical" ? "text-critical" : tone === "accent" ? "text-accent" : "text-foreground";
  return (
    <Card className="px-5 py-4">
      <div className="text-[11px] font-medium uppercase tracking-wide text-subtle">{label}</div>
      <div className={`mt-2 font-mono text-2xl font-semibold tabular-nums ${color}`}>{value}</div>
      {hint ? <div className="mt-1 text-xs text-muted">{hint}</div> : null}
    </Card>
  );
}

export default function OverviewPage() {
  const { data, error, loading, refresh } = useQuery(
    () => Promise.all([api.metrics(), api.workflows({ limit: 8 }), api.health()]),
    [],
  );
  const metrics = data?.[0] ?? null;
  const recent = data?.[1].items ?? [];
  const health = data?.[2] ?? null;

  return (
    <AppShell>
      <PageHeader
        title="Overview"
        description="Live operational metrics computed from stored workflow, approval, execution and audit records."
        actions={
          <>
            <Button variant="secondary" size="sm" onClick={refresh} disabled={loading}>
              <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
            </Button>
            <Link href="/playground">
              <Button size="sm">
                Open playground <ArrowRight className="h-3.5 w-3.5" />
              </Button>
            </Link>
          </>
        }
      />
      <ErrorBanner message={error} />
      {!metrics ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-6 w-6" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
            <MetricCard label="Total workflows" value={metrics.total_workflows} />
            <MetricCard label="Completed" value={metrics.completed_workflows} tone="success" hint={`${formatINR(metrics.total_refunded_paise)} refunded (simulated)`} />
            <MetricCard label="Pending approvals" value={metrics.pending_approvals} tone="warning" />
            <MetricCard label="Failed" value={metrics.failed_workflows} tone="critical" hint={`${metrics.rejected_workflows} rejected by policy/reviewers`} />
            <MetricCard label="Blocked unauthorized actions" value={metrics.blocked_unauthorized_actions} tone="critical" hint={`${metrics.injection_attempts_detected} injection attempts flagged`} />
            <MetricCard label="Avg. workflow duration" value={formatDuration(metrics.average_workflow_duration_ms)} tone="accent" hint="completed workflows only" />
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader title="Workflows per day" description="Last 14 days, stacked by outcome" />
              <CardBody>
                <WorkflowsPerDayChart data={metrics.workflows_per_day} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title="Workflows by state" description="Current state of every stored workflow" />
              <CardBody>
                <StateDistributionChart data={metrics.workflows_by_state} />
              </CardBody>
            </Card>
          </div>
          <Card>
            <CardHeader
              title="Recent workflows"
              actions={
                <Link href="/workflows" className="text-xs text-accent hover:underline">
                  View all
                </Link>
              }
            />
            <WorkflowTable workflows={recent} />
          </Card>
          <Card>
            <CardHeader title="System" description="Live configuration reported by the API" />
            <CardBody className="grid gap-x-8 gap-y-3 text-sm sm:grid-cols-2 xl:grid-cols-3">
              <Row label="Environment" value={health?.environment ?? "—"} />
              <Row label="Database" value={health?.database ?? "—"} />
              <Row label="AI provider" value={`${health?.ai_provider.name ?? "—"} · ${health?.ai_provider.model ?? ""}`} />
              <Row label="Demo mode" value={health?.demo_mode ? "on (seeded fictional data)" : "off"} />
              <Row
                label="Policy outcomes"
                value={
                  Object.entries(metrics.policy_outcomes)
                    .map(([k, v]) => `${k}: ${v}`)
                    .join(" · ") || "—"
                }
              />
              <Row label="API version" value={health?.version ?? "—"} />
            </CardBody>
          </Card>
        </div>
      )}
    </AppShell>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-border/60 pb-2">
      <span className="text-xs text-subtle">{label}</span>
      <span className="text-right font-mono text-xs text-muted">{value}</span>
    </div>
  );
}
