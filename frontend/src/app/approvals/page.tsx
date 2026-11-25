"use client";

import { Check, X } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Label, Textarea } from "@/components/ui/input";
import { Dialog, EmptyState, ErrorBanner, PageHeader, Spinner } from "@/components/ui/misc";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { ApprovalStatusBadge } from "@/components/workflow-bits";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";
import { useAuth } from "@/lib/auth";
import { formatDateTime, formatINR, humanize, roleLabel, shortId } from "@/lib/format";
import type { Approval } from "@/lib/types";

export default function ApprovalsPage() {
  const { user } = useAuth();
  const { data, error: loadError, refresh } = useQuery(() => Promise.all([api.approvals("pending"), api.approvals()]), []);
  const pending = data ? data[0] : null;
  const history = data ? data[1].filter((a) => a.status !== "pending") : [];
  const [error, setError] = useState<string | null>(null);
  const [active, setActive] = useState<{ approval: Approval; decision: "approve" | "reject" } | null>(null);
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);

  function canDecide(approval: Approval): boolean {
    if (!user) return false;
    const needed = approval.required_role === "senior_reviewer" ? "approval:decide:senior" : "approval:decide:standard";
    return user.permissions.includes(needed);
  }

  async function submitDecision() {
    if (!active) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const workflow = await api.decide(active.approval.id, active.decision, comment);
      setNotice(`Approval ${active.decision === "approve" ? "granted" : "rejected"} · workflow is now ${workflow.state}.`);
      setActive(null);
      setComment("");
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Decision failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        title="Approval Center"
        description="Human-in-the-loop decisions. The backend verifies your role against each approval's required role, so the buttons below are a convenience, not the control."
      />
      <ErrorBanner message={error ?? loadError} />
      {notice ? <div className="mb-4 rounded-md border border-success/40 bg-success/10 px-3 py-2 text-sm text-success">{notice}</div> : null}
      <div className="space-y-6">
        <Card>
          <CardHeader title={`Pending approvals${pending ? ` (${pending.length})` : ""}`} description={`Signed in as ${user?.display_name ?? ""} · ${roleLabel(user?.role)}`} />
          {pending === null ? (
            <div className="flex justify-center py-10">
              <Spinner />
            </div>
          ) : pending.length === 0 ? (
            <EmptyState title="Nothing waiting for review" description="Submit a request above ₹2,000 in the playground to create one." />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Requested</Th>
                  <Th>Customer / order</Th>
                  <Th>Amount</Th>
                  <Th>Requires</Th>
                  <Th>Reason</Th>
                  <Th>Context</Th>
                  <Th>Expires</Th>
                  <Th className="text-right">Decision</Th>
                </tr>
              </thead>
              <tbody>
                {pending.map((a) => {
                  const details = (a.details ?? {}) as Record<string, unknown>;
                  const discrepancies = (details.discrepancies as string[] | undefined) ?? [];
                  const flags = (details.flags as string[] | undefined) ?? [];
                  const allowed = canDecide(a);
                  return (
                    <Tr key={a.id}>
                      <Td className="whitespace-nowrap font-mono text-[11px] text-subtle">{formatDateTime(a.requested_at)}</Td>
                      <Td>
                        <div className="text-sm">{a.customer_name ?? a.customer_id}</div>
                        <Link href={`/workflows/${a.workflow_id}`} className="font-mono text-[11px] text-accent hover:underline">
                          {a.order_id} · {shortId(a.workflow_id)}
                        </Link>
                      </Td>
                      <Td className="font-mono text-sm">{formatINR(a.amount_paise)}</Td>
                      <Td>
                        <Badge tone={a.required_role === "senior_reviewer" ? "serious" : "warning"}>{roleLabel(a.required_role)}</Badge>
                      </Td>
                      <Td className="text-xs text-muted">{humanize(a.reason)}</Td>
                      <Td className="max-w-xs">
                        <div className="flex flex-wrap gap-1">
                          {discrepancies.map((d) => (
                            <Badge key={d} tone="critical" className="normal-case tracking-normal">
                              {d}
                            </Badge>
                          ))}
                          {flags.map((f) => (
                            <Badge key={f} tone="warning" className="normal-case tracking-normal">
                              {f}
                            </Badge>
                          ))}
                        </div>
                        {typeof details.agent_summary === "string" ? <p className="mt-1 line-clamp-2 text-[11px] text-subtle">{details.agent_summary}</p> : null}
                      </Td>
                      <Td className="whitespace-nowrap font-mono text-[11px] text-subtle">{formatDateTime(a.expires_at)}</Td>
                      <Td className="text-right">
                        <div className="flex justify-end gap-2">
                          <Button size="sm" variant="success" disabled={!allowed} title={allowed ? "" : `Requires ${roleLabel(a.required_role)}`} onClick={() => setActive({ approval: a, decision: "approve" })}>
                            <Check className="h-3.5 w-3.5" /> Approve
                          </Button>
                          <Button size="sm" variant="danger" disabled={!allowed} title={allowed ? "" : `Requires ${roleLabel(a.required_role)}`} onClick={() => setActive({ approval: a, decision: "reject" })}>
                            <X className="h-3.5 w-3.5" /> Reject
                          </Button>
                        </div>
                      </Td>
                    </Tr>
                  );
                })}
              </tbody>
            </Table>
          )}
        </Card>
        <Card>
          <CardHeader title="Approval history" description="Every decision is recorded with the authenticated reviewer's identity." />
          {history.length === 0 ? (
            <EmptyState title="No decisions yet" />
          ) : (
            <Table>
              <thead>
                <tr>
                  <Th>Decided</Th>
                  <Th>Workflow</Th>
                  <Th>Amount</Th>
                  <Th>Status</Th>
                  <Th>Decided by</Th>
                  <Th>Comment</Th>
                </tr>
              </thead>
              <tbody>
                {history.map((a) => (
                  <Tr key={a.id}>
                    <Td className="whitespace-nowrap font-mono text-[11px] text-subtle">{formatDateTime(a.decided_at ?? a.requested_at)}</Td>
                    <Td>
                      <Link href={`/workflows/${a.workflow_id}`} className="font-mono text-xs text-accent hover:underline">
                        {shortId(a.workflow_id)}
                      </Link>
                      <div className="text-[11px] text-subtle">{a.customer_name ?? a.customer_id}</div>
                    </Td>
                    <Td className="font-mono text-xs">{formatINR(a.amount_paise)}</Td>
                    <Td>
                      <ApprovalStatusBadge status={a.status} />
                    </Td>
                    <Td className="text-xs">
                      {a.decided_by_name ?? a.decided_by ?? "—"}
                      {a.decided_by_role ? <span className="text-subtle"> · {roleLabel(a.decided_by_role)}</span> : null}
                      {a.auto ? <span className="text-subtle"> · auto</span> : null}
                    </Td>
                    <Td className="max-w-sm text-xs text-muted">{a.comment ?? "—"}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
      </div>
      <Dialog open={active !== null} onClose={() => setActive(null)} title={active ? `${active.decision === "approve" ? "Approve" : "Reject"} refund of ${formatINR(active.approval.amount_paise)}` : ""}>
        {active ? (
          <div className="space-y-4">
            <p className="text-sm text-muted">
              {active.approval.customer_name} · order {active.approval.order_id} · requires {roleLabel(active.approval.required_role)}.
              {active.decision === "approve" ? " Approving will immediately execute the simulated refund." : " Rejecting ends the workflow; it cannot be executed afterwards."}
            </p>
            <div>
              <Label htmlFor="comment">Comment</Label>
              <Textarea id="comment" value={comment} onChange={(e) => setComment(e.target.value)} className="min-h-[80px]" placeholder="Why are you making this decision?" />
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="secondary" onClick={() => setActive(null)}>
                Back
              </Button>
              <Button variant={active.decision === "approve" ? "success" : "danger"} disabled={busy} onClick={submitDecision}>
                {busy ? "Submitting…" : active.decision === "approve" ? "Confirm approval" : "Confirm rejection"}
              </Button>
            </div>
          </div>
        ) : null}
      </Dialog>
    </AppShell>
  );
}
