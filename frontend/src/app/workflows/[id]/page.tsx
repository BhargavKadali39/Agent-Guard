"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Label } from "@/components/ui/input";
import { Dialog, ErrorBanner, JsonView, KeyValue, PageHeader, Spinner } from "@/components/ui/misc";
import { ApprovalStatusBadge, StateBadge } from "@/components/workflow-bits";
import { ResultPanel } from "@/components/workflow-result";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatINR, humanize, roleLabel } from "@/lib/format";
import type { Workflow } from "@/lib/types";

const WorkflowGraph = dynamic(() => import("@/components/workflow-graph").then((m) => m.WorkflowGraph), {
  ssr: false,
  loading: () => (
    <div className="flex h-[420px] items-center justify-center rounded-md border border-border">
      <Spinner />
    </div>
  ),
});

export default function WorkflowDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params.id;
  const { can } = useAuth();
  const { data, error: loadError, refresh } = useQuery(() => Promise.all([api.workflow(id), api.workflowEvents(id)]), [id]);
  const workflow = data?.[0] ?? null;
  const events = useMemo(() => data?.[1].items ?? [], [data]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState("cancelled by operator");
  const [notice, setNotice] = useState<string | null>(null);

  const transitions = useMemo(
    () =>
      events
        .filter((e) => e.event_type === "workflow.transition" && e.payload)
        .map((e) => ({ from: String(e.payload?.from), to: String(e.payload?.to) })),
    [events],
  );

  async function act(action: () => Promise<Workflow>, label: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const updated = await action();
      setNotice(updated.interrupted ? `${label}: simulated interruption fired again; state persisted at ${updated.state}.` : `${label}: now ${updated.state}.`);
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} failed`);
    } finally {
      setBusy(false);
    }
  }

  if (!workflow) {
    return (
      <AppShell>
        <ErrorBanner message={error ?? loadError} />
        {!loadError ? (
          <div className="flex justify-center py-20">
            <Spinner className="h-6 w-6" />
          </div>
        ) : null}
      </AppShell>
    );
  }

  const resumable = ["CREATED", "ANALYZING", "VERIFYING", "POLICY_CHECK", "APPROVED", "EXECUTING"].includes(workflow.state) || (workflow.state === "FAILED" && workflow.resumable);
  const cancellable = !["COMPLETED", "REJECTED", "CANCELLED", "EXECUTING"].includes(workflow.state);

  return (
    <AppShell>
      <PageHeader
        title={`Workflow ${workflow.id.slice(0, 8)}`}
        description={`${workflow.customer_name ?? workflow.customer_id} · created ${formatDateTime(workflow.created_at)} · provider ${workflow.provider_name}`}
        actions={
          <>
            <StateBadge state={workflow.state} />
            {resumable && can("workflow:resume") ? (
              <Button size="sm" disabled={busy} onClick={() => act(() => api.resumeWorkflow(workflow.id), "Resume")}>
                Resume from checkpoint
              </Button>
            ) : null}
            {cancellable && can("workflow:cancel") ? (
              <Button size="sm" variant="danger" disabled={busy} onClick={() => setCancelOpen(true)}>
                Cancel
              </Button>
            ) : null}
          </>
        }
      />
      <ErrorBanner message={error} />
      {notice ? <div className="mb-4 rounded-md border border-accent/40 bg-accent-soft px-3 py-2 text-sm text-accent">{notice}</div> : null}
      <div className="space-y-6">
        <Card>
          <CardHeader title="State machine" description="Animated edges are the transitions this workflow actually took (from its audit trail). Failure, cancel and resume edges appear only when taken." />
          <CardBody>
            <WorkflowGraph current={workflow.state} transitions={transitions} />
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Customer message (untrusted input)" />
          <CardBody>
            <p className="whitespace-pre-wrap rounded-md border border-border bg-background p-3 font-mono text-xs text-muted">{workflow.message}</p>
          </CardBody>
        </Card>
        <ResultPanel workflow={workflow} events={events} httpStatus={null} />
        <div className="grid gap-6 lg:grid-cols-2">
          <Card>
            <CardHeader title="Approvals" description="Each approval is bound to this workflow, order and amount." />
            <CardBody className="space-y-3">
              {workflow.approvals.length === 0 ? <p className="text-sm text-muted">No approvals raised.</p> : null}
              {workflow.approvals.map((a) => (
                <div key={a.id} className="rounded-md border border-border bg-background p-3 text-sm">
                  <div className="flex flex-wrap items-center gap-2">
                    <ApprovalStatusBadge status={a.status} />
                    <span className="font-mono text-xs">{formatINR(a.amount_paise)}</span>
                    <span className="text-xs text-muted">requires {roleLabel(a.required_role)}</span>
                    <span className="text-xs text-subtle">· {humanize(a.reason)}</span>
                    {a.auto ? <span className="text-xs text-subtle">· auto</span> : null}
                  </div>
                  {a.decided_by ? (
                    <div className="mt-1 text-xs text-muted">
                      Decided by {a.decided_by_name ?? a.decided_by} ({roleLabel(a.decided_by_role)}) at {formatDateTime(a.decided_at)}
                      {a.comment ? ` — “${a.comment}”` : ""}
                    </div>
                  ) : (
                    <div className="mt-1 text-xs text-muted">Expires {formatDateTime(a.expires_at)}</div>
                  )}
                </div>
              ))}
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Checkpoint & execution" description="What a resume would pick up from." />
            <CardBody className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <KeyValue label="Checkpoint step" value={workflow.checkpoint?.step ?? "—"} mono />
                <KeyValue label="Resume target" value={workflow.checkpoint?.resume_target ?? (workflow.state === "FAILED" ? "—" : workflow.state)} mono />
                <KeyValue label="Resumes" value={workflow.resume_count} />
                <KeyValue label="Client request id" value={workflow.client_request_id ?? "—"} mono />
              </div>
              {workflow.failure_reason ? <p className="text-xs text-serious">Failure: {workflow.failure_reason}</p> : null}
              {workflow.execution ? (
                <div className="rounded-md border border-success/30 bg-success/10 p-3 text-xs">
                  <div className="font-medium text-success">Simulated refund executed</div>
                  <div className="mt-1 font-mono text-muted">
                    {formatINR(workflow.execution.amount_paise)} · {workflow.execution.gateway_reference} · key {workflow.execution.idempotency_key}
                  </div>
                </div>
              ) : null}
              {workflow.simulation ? (
                <div>
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-subtle">Simulation config</div>
                  <JsonView value={workflow.simulation} className="max-h-40" />
                </div>
              ) : null}
            </CardBody>
          </Card>
        </div>
      </div>
      <Dialog open={cancelOpen} onClose={() => setCancelOpen(false)} title="Cancel workflow">
        <div className="space-y-4">
          <div>
            <Label htmlFor="reason">Reason</Label>
            <Input id="reason" value={cancelReason} onChange={(e) => setCancelReason(e.target.value)} />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setCancelOpen(false)}>
              Keep
            </Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={async () => {
                setCancelOpen(false);
                await act(() => api.cancelWorkflow(workflow.id, cancelReason), "Cancel");
              }}
            >
              Cancel workflow
            </Button>
          </div>
        </div>
      </Dialog>
    </AppShell>
  );
}
