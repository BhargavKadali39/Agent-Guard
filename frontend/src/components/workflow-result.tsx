"use client";

import Link from "next/link";

import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { KeyValue } from "@/components/ui/misc";
import { EventTimeline, Flag, StateBadge } from "@/components/workflow-bits";
import { formatINR, humanize, reasonText } from "@/lib/format";
import type { AuditEvent, Workflow } from "@/lib/types";

export function ResultPanel({ workflow, events, httpStatus }: { workflow: Workflow; events: AuditEvent[]; httpStatus: string | null }) {
  const interp = workflow.interpretation;
  const verification = workflow.verification;
  const policy = workflow.policy_decision;
  const pending = workflow.approvals.find((a) => a.status === "pending");
  return (
    <>
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-3">
              Outcome <StateBadge state={workflow.state} />
            </span>
          }
          description={httpStatus ?? `Workflow ${workflow.id}`}
          actions={
            <Link href={`/workflows/${workflow.id}`} className="text-xs text-accent hover:underline">
              Open in explorer
            </Link>
          }
        />
        <CardBody className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <KeyValue label="Verified order" value={workflow.order_id ?? "not identified"} mono />
          <KeyValue label="Proposed amount" value={formatINR(verification?.amount_paise)} />
          <KeyValue label="Policy tier" value={policy ? `${policy.tier}${policy.required_role ? ` · ${humanize(policy.required_role)}` : ""}` : "—"} />
          <KeyValue
            label="Result"
            value={
              workflow.execution
                ? `Refunded ${formatINR(workflow.execution.amount_paise)} (${workflow.execution.gateway_reference})`
                : pending
                  ? `Waiting for ${humanize(pending.required_role)} (${humanize(pending.reason)})`
                  : workflow.rejection_reason
                    ? reasonText(workflow.rejection_reason)
                    : workflow.failure_reason
                      ? workflow.failure_reason
                      : workflow.interrupted
                        ? "interrupted · resume from the explorer"
                        : "—"
            }
          />
        </CardBody>
      </Card>
      <div className="grid gap-6 lg:grid-cols-3">
        <Card>
          <CardHeader title="1 · Agent proposes" description={`${interp?.provider ?? "—"} · ${interp?.model ?? ""}`} />
          <CardBody className="space-y-3 text-sm">
            {interp ? (
              <>
                <p className="text-muted">{interp.summary}</p>
                <div className="grid grid-cols-2 gap-3">
                  <KeyValue label="Intent" value={humanize(interp.intent)} />
                  <KeyValue label="Confidence" value={`${Math.round(interp.confidence * 100)}%`} />
                  <KeyValue label="Order mentioned" value={interp.order_id ?? "—"} mono />
                  <KeyValue label="Amount mentioned" value={formatINR(interp.requested_amount_paise)} />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {interp.suspected_injection ? <Flag tone="critical">suspected injection</Flag> : null}
                  {interp.conflicting_statements.map((c) => (
                    <Flag key={c}>{c}</Flag>
                  ))}
                </div>
                <div>
                  <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-subtle">Proposed tool calls</div>
                  <ul className="space-y-1 break-all font-mono text-[11px]">
                    {interp.proposed_tool_calls.map((p, i) => (
                      <li key={i} className="text-muted">
                        <span className="text-accent">{p.tool}</span>({Object.entries(p.arguments).map(([k, v]) => `${k}=${JSON.stringify(v)}`).join(", ")})
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            ) : (
              <p className="text-muted">Not reached.</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="2 · Backend verifies" description="Interpretation cross-checked against trusted order data" />
          <CardBody className="space-y-3 text-sm">
            {verification ? (
              <>
                <div className="grid grid-cols-2 gap-3">
                  <KeyValue label="Order" value={verification.order_id ?? "—"} mono />
                  <KeyValue label="Refundable" value={formatINR(verification.refundable_paise)} />
                  <KeyValue label="Requested" value={formatINR(verification.requested_amount_paise)} />
                  <KeyValue label="Proposed" value={formatINR(verification.amount_paise)} />
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {verification.discrepancies.map((d) => (
                    <Flag key={d} tone="critical">
                      {d}
                    </Flag>
                  ))}
                  {verification.flags.map((f) => (
                    <Flag key={f}>{f}</Flag>
                  ))}
                  {verification.requires_human_review ? (
                    <Badge tone="warning" className="whitespace-normal">
                      human review: {humanize(verification.review_reason)}
                    </Badge>
                  ) : null}
                </div>
              </>
            ) : (
              <p className="text-muted">Not reached.</p>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="3 · Policy decides" description={policy ? `${policy.policy_name} v${policy.policy_version}` : "Deterministic rules"} />
          <CardBody className="space-y-2 text-sm">
            {policy ? (
              <>
                <div className="flex items-center gap-2">
                  <Badge tone={policy.eligible ? "success" : "critical"}>{policy.eligible ? "eligible" : "not eligible"}</Badge>
                  <Badge tone="info">{policy.tier}</Badge>
                </div>
                <ul className="space-y-2 text-xs">
                  {policy.rules.map((r) => (
                    <li key={r.rule}>
                      <div className="flex items-center gap-2">
                        <span className={r.passed ? "text-success" : "text-critical"} aria-label={r.passed ? "passed" : "failed"}>
                          {r.passed ? "✓" : "✗"}
                        </span>
                        <span className="break-all font-mono text-muted">{r.rule}</span>
                      </div>
                      <div className="ml-5 text-subtle">{r.detail}</div>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="text-muted">Not reached.</p>
            )}
          </CardBody>
        </Card>
      </div>
      <Card>
        <CardHeader title="Audit timeline" description={`${events.length} structured events recorded for this workflow`} />
        <EventTimeline events={events} compact />
      </Card>
    </>
  );
}
