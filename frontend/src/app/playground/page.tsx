"use client";

import { Send, Sparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { Input, Label, Select, Textarea } from "@/components/ui/input";
import { ErrorBanner, PageHeader, Spinner } from "@/components/ui/misc";
import { ResultPanel } from "@/components/workflow-result";
import { api } from "@/lib/api";
import { formatINR } from "@/lib/format";
import type { AuditEvent, Customer, ExampleRequest, Order, SimulationConfig, Workflow } from "@/lib/types";

const SIMULATIONS: { key: string; label: string; config: SimulationConfig | null }[] = [
  { key: "none", label: "No simulated failure", config: null },
  { key: "gateway", label: "Payment gateway times out once (auto-retry)", config: { gateway_fail_times: 1 } },
  { key: "exhaust", label: "Refund tool fails 5× (exhausts retries → FAILED, resumable)", config: { fail_tool: "execute_simulated_refund", fail_times: 5 } },
  { key: "db", label: "Database fails before commit (no partial refund)", config: { db_fail_times: 1 } },
  { key: "interrupt_policy", label: "Crash after POLICY_CHECK", config: { interrupt_after: "POLICY_CHECK" } },
  { key: "interrupt_commit", label: "Crash after the refund committed (EXECUTION_COMMIT)", config: { interrupt_after: "EXECUTION_COMMIT" } },
  { key: "misread", label: "Agent misreads the amount ×10", config: { provider_fault: "misread_amount" } },
  { key: "wrong_intent", label: "Agent misclassifies the intent", config: { provider_fault: "wrong_intent" } },
  { key: "low_conf", label: "Agent reports low confidence", config: { provider_fault: "low_confidence" } },
];

export default function PlaygroundPage() {
  const [customers, setCustomers] = useState<Customer[]>([]);
  const [orders, setOrders] = useState<Order[]>([]);
  const [examples, setExamples] = useState<ExampleRequest[]>([]);
  const [customerId, setCustomerId] = useState("");
  const [message, setMessage] = useState("");
  const [clientRequestId, setClientRequestId] = useState("");
  const [simulation, setSimulation] = useState("none");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<Workflow | null>(null);
  const [events, setEvents] = useState<AuditEvent[]>([]);
  const [httpStatus, setHttpStatus] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([api.customers(), api.examples()])
      .then(([c, e]) => {
        setCustomers(c.filter((x) => !x.id.startsWith("CUST-LAB")));
        setExamples(e);
        if (c.length) setCustomerId(c[0].id);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, []);

  useEffect(() => {
    if (!customerId) return;
    api.customerOrders(customerId).then(setOrders).catch(() => setOrders([]));
  }, [customerId]);

  const simulationConfig = useMemo(() => SIMULATIONS.find((s) => s.key === simulation)?.config ?? null, [simulation]);

  function applyExample(example: ExampleRequest) {
    setCustomerId(example.customer_id);
    setMessage(example.message);
    const exampleSimulation = example.simulation;
    setSimulation(
      exampleSimulation
        ? (SIMULATIONS.find((s) => JSON.stringify(s.config) === JSON.stringify(stripDefaults(exampleSimulation)))?.key ?? "none")
        : "none",
    );
    setResult(null);
    setEvents([]);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    setHttpStatus(null);
    try {
      const workflow = await api.submitWorkflow({
        customer_id: customerId,
        message,
        client_request_id: clientRequestId.trim() || undefined,
        simulation: simulationConfig,
      });
      setResult(workflow);
      setHttpStatus(workflow.interrupted ? "202 Accepted · simulated interruption, state persisted" : null);
      const ev = await api.workflowEvents(workflow.id);
      setEvents(ev.items);
      const refreshed = await api.customerOrders(customerId);
      setOrders(refreshed);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Submission failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <AppShell>
      <PageHeader
        title="Agent Playground"
        description="Submit a fictional customer request. The agent interprets it, the backend verifies, applies policy, asks for approval when required and executes a simulated refund."
      />
      <ErrorBanner message={error} />
      <div className="mt-4 grid gap-6 xl:grid-cols-5">
        <div className="space-y-6 xl:col-span-2">
          <Card>
            <CardHeader title="New refund request" description="The customer identity is trusted (selected here); the message is untrusted input." />
            <CardBody className="space-y-4">
              <div>
                <Label htmlFor="customer">Customer (trusted)</Label>
                <Select id="customer" value={customerId} onChange={(e) => setCustomerId(e.target.value)}>
                  {customers.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} · {c.id} · {c.city}
                    </option>
                  ))}
                </Select>
              </div>
              {orders.length ? (
                <div className="rounded-md border border-border bg-background p-3">
                  <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-subtle">Customer&apos;s orders</div>
                  <ul className="space-y-1 text-xs">
                    {orders.map((o) => (
                      <li key={o.id} className="flex items-center justify-between gap-2">
                        <span className="font-mono text-accent">{o.id}</span>
                        <span className="flex-1 truncate text-muted">{o.product_name}</span>
                        <span className="font-mono">{formatINR(o.total_paise)}</span>
                        <Badge tone={o.status === "DELIVERED" ? "success" : "neutral"}>{o.status}</Badge>
                        <span className="w-24 text-right font-mono text-[11px] text-subtle">
                          {o.refundable_paise === o.total_paise ? "" : `${formatINR(o.refundable_paise)} left`}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : null}
              <div>
                <Label htmlFor="message">Customer message (untrusted)</Label>
                <Textarea id="message" value={message} onChange={(e) => setMessage(e.target.value)} placeholder="I purchased headphones worth ₹8,500 last week, but they arrived damaged. Please process a refund." />
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div>
                  <Label htmlFor="simulation">Failure simulation</Label>
                  <Select id="simulation" value={simulation} onChange={(e) => setSimulation(e.target.value)}>
                    {SIMULATIONS.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                </div>
                <div>
                  <Label htmlFor="crid">Client request id (optional, idempotency)</Label>
                  <Input id="crid" value={clientRequestId} onChange={(e) => setClientRequestId(e.target.value)} placeholder="e.g. ticket-4821" />
                </div>
              </div>
              <Button onClick={submit} disabled={busy || !message.trim() || !customerId} className="w-full">
                {busy ? <Spinner className="text-white" /> : <Send className="h-4 w-4" />}
                {busy ? "Running agent workflow…" : "Submit request"}
              </Button>
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Example requests" description="Seeded scenarios that exercise policy tiers, injection, ambiguity and failures." />
            <ul className="divide-y divide-border">
              {examples.map((ex) => (
                <li key={ex.key}>
                  <button type="button" onClick={() => applyExample(ex)} className="flex w-full items-start gap-3 px-5 py-3 text-left hover:bg-surface-raised">
                    <Sparkles className="mt-0.5 h-4 w-4 shrink-0 text-accent" />
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{ex.title}</div>
                      <div className="mt-0.5 line-clamp-2 text-xs text-muted">{ex.expected}</div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          </Card>
        </div>
        <div className="space-y-6 xl:col-span-3">
          {!result ? (
            <Card>
              <CardBody className="py-16 text-center text-sm text-muted">
                Submit a request to see the agent&apos;s interpretation, the verification, the policy decision and the audit timeline.
              </CardBody>
            </Card>
          ) : (
            <ResultPanel workflow={result} events={events} httpStatus={httpStatus} />
          )}
        </div>
      </div>
    </AppShell>
  );
}

function stripDefaults(simulation: SimulationConfig): SimulationConfig {
  const out: SimulationConfig = {};
  if (simulation.fail_tool) out.fail_tool = simulation.fail_tool;
  if (simulation.fail_times) out.fail_times = simulation.fail_times;
  if (simulation.gateway_fail_times) out.gateway_fail_times = simulation.gateway_fail_times;
  if (simulation.db_fail_times) out.db_fail_times = simulation.db_fail_times;
  if (simulation.interrupt_after) out.interrupt_after = simulation.interrupt_after;
  if (simulation.provider_fault) out.provider_fault = simulation.provider_fault;
  return out;
}
