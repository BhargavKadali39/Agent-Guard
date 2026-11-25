"use client";

import { CheckCircle2, FlaskConical, Play, XCircle } from "lucide-react";
import Link from "next/link";
import { useMemo, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner, PageHeader, Spinner } from "@/components/ui/misc";
import { EventTimeline } from "@/components/workflow-bits";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";
import { formatDateTime, formatDuration, shortId } from "@/lib/format";
import type { ScenarioResult } from "@/lib/types";

const CATEGORY_TONE = { security: "critical", reliability: "info", governance: "warning", evaluation: "serious" } as const;

export default function FailureLabPage() {
  const { data, error: loadError, refresh } = useQuery(() => Promise.all([api.scenarios(), api.labRuns()]), []);
  const scenarios = useMemo(() => data?.[0] ?? [], [data]);
  const runs = data?.[1] ?? [];
  const [results, setResults] = useState<Record<string, ScenarioResult>>({});
  const [running, setRunning] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const selected = chosen ?? scenarios[0]?.key ?? null;
  const setSelected = setChosen;

  async function run(key: string) {
    setRunning(key);
    setSelected(key);
    setError(null);
    try {
      const result = await api.runScenario(key);
      setResults((prev) => ({ ...prev, [key]: result }));
      refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Scenario run failed");
    } finally {
      setRunning(null);
    }
  }

  async function runAll() {
    for (const scenario of scenarios) {
      await run(scenario.key);
    }
  }

  const current = selected ? scenarios.find((s) => s.key === selected) : null;
  const currentResult = selected ? results[selected] : undefined;

  return (
    <AppShell>
      <PageHeader
        title="Failure Lab"
        description="Six controlled failure scenarios run against the real workflow engine. A scenario passes only when every executable assertion passes; nothing is hardcoded."
        actions={
          <Button onClick={runAll} disabled={running !== null || scenarios.length === 0}>
            <Play className="h-4 w-4" /> Run all scenarios
          </Button>
        }
      />
      <ErrorBanner message={error ?? loadError} />
      <div className="grid gap-6 xl:grid-cols-5">
        <div className="space-y-3 xl:col-span-2">
          {scenarios.map((scenario, index) => {
            const result = results[scenario.key];
            const isRunning = running === scenario.key;
            return (
              <Card key={scenario.key} className={`cursor-pointer transition-colors ${selected === scenario.key ? "border-accent" : "hover:border-border-strong"}`} onClick={() => setSelected(scenario.key)}>
                <CardBody className="flex items-start gap-4">
                  <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface-raised font-mono text-sm text-muted">{index + 1}</div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-semibold">{scenario.title}</span>
                      <Badge tone={CATEGORY_TONE[scenario.category as keyof typeof CATEGORY_TONE] ?? "neutral"}>{scenario.category}</Badge>
                      {result ? (
                        result.passed ? (
                          <Badge tone="success">
                            <CheckCircle2 className="h-3 w-3" /> passed
                          </Badge>
                        ) : (
                          <Badge tone="critical">
                            <XCircle className="h-3 w-3" /> failed
                          </Badge>
                        )
                      ) : null}
                    </div>
                    <p className="mt-1 text-xs text-muted">{scenario.description}</p>
                  </div>
                  <Button
                    size="sm"
                    variant="secondary"
                    disabled={running !== null}
                    onClick={(e) => {
                      e.stopPropagation();
                      void run(scenario.key);
                    }}
                  >
                    {isRunning ? <Spinner /> : <Play className="h-3.5 w-3.5" />}
                    Run
                  </Button>
                </CardBody>
              </Card>
            );
          })}
          <Card>
            <CardHeader title="Run history" description="Persisted results of previous runs" />
            {runs.length === 0 ? (
              <p className="px-5 py-4 text-sm text-muted">No runs yet.</p>
            ) : (
              <ul className="divide-y divide-border text-xs">
                {runs.slice(0, 12).map((r) => (
                  <li key={r.id} className="flex items-center justify-between px-5 py-2">
                    <span className="font-mono text-muted">{r.scenario_key}</span>
                    <span className="text-subtle">{formatDateTime(r.started_at)}</span>
                    <span className="font-mono text-subtle">{formatDuration(r.duration_ms)}</span>
                    <Badge tone={r.passed ? "success" : "critical"}>{r.passed ? "pass" : "fail"}</Badge>
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="space-y-6 xl:col-span-3">
          {current ? (
            <>
              <Card>
                <CardHeader
                  title={
                    <span className="flex items-center gap-2">
                      <FlaskConical className="h-4 w-4 text-accent" /> {current.title}
                    </span>
                  }
                  description={current.description}
                />
                <CardBody className="space-y-4 text-sm">
                  <Section label="Initial request">
                    <p className="rounded-md border border-border bg-background p-3 font-mono text-xs text-muted">{current.initial_request}</p>
                  </Section>
                  <Section label="Expected safe behavior">
                    <p className="text-muted">{current.expected_behavior}</p>
                  </Section>
                  <Section label="Observed application behavior">
                    {currentResult ? (
                      <p className="text-muted">{currentResult.observed_behavior}</p>
                    ) : running === current.key ? (
                      <p className="flex items-center gap-2 text-muted">
                        <Spinner /> Running real workflows…
                      </p>
                    ) : (
                      <p className="text-subtle">Run the scenario to observe.</p>
                    )}
                  </Section>
                  <Section label="Why this matters">
                    <p className="text-muted">{current.explanation}</p>
                  </Section>
                </CardBody>
              </Card>
              {currentResult ? (
                <>
                  <Card>
                    <CardHeader
                      title={
                        <span className="flex items-center gap-2">
                          Safety assertions
                          {currentResult.passed ? <Badge tone="success">all passed</Badge> : <Badge tone="critical">failed</Badge>}
                        </span>
                      }
                      description={`${currentResult.assertions.filter((a) => a.passed).length}/${currentResult.assertions.length} passed · ${formatDuration(currentResult.duration_ms)} · workflows: ${currentResult.workflow_ids.map((id) => shortId(id)).join(", ")}`}
                    />
                    <ul className="divide-y divide-border">
                      {currentResult.assertions.map((a) => (
                        <li key={a.name} className="flex items-start gap-3 px-5 py-2.5">
                          {a.passed ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" /> : <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-critical" />}
                          <div>
                            <div className="font-mono text-xs">{a.name}</div>
                            <div className="text-xs text-muted">{a.detail}</div>
                          </div>
                        </li>
                      ))}
                    </ul>
                    <div className="flex flex-wrap gap-3 border-t border-border px-5 py-3 text-xs">
                      {currentResult.workflow_ids.map((id) => (
                        <Link key={id} href={`/workflows/${id}`} className="font-mono text-accent hover:underline">
                          open workflow {shortId(id)}
                        </Link>
                      ))}
                    </div>
                  </Card>
                  <Card>
                    <CardHeader title="Relevant workflow events" description={`${currentResult.events.length} audit events across the scenario's workflows`} />
                    <div className="scrollbar-thin max-h-[560px] overflow-auto">
                      <EventTimeline events={currentResult.events} compact />
                    </div>
                  </Card>
                </>
              ) : null}
            </>
          ) : null}
        </div>
      </div>
    </AppShell>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-subtle">{label}</div>
      {children}
    </div>
  );
}
