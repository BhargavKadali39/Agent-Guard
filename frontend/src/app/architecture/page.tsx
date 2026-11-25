"use client";

import { Check, Minus } from "lucide-react";
import dynamic from "next/dynamic";
import { useEffect, useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Badge } from "@/components/ui/badge";
import { Card, CardBody, CardHeader } from "@/components/ui/card";
import { ErrorBanner, PageHeader, Spinner } from "@/components/ui/misc";
import { Table, Td, Th, Tr } from "@/components/ui/table";
import { api } from "@/lib/api";
import { roleLabel } from "@/lib/format";
import type { Architecture } from "@/lib/types";

const ArchitectureGraph = dynamic(() => import("@/components/architecture-graph").then((m) => m.ArchitectureGraph), { ssr: false });
const WorkflowGraph = dynamic(() => import("@/components/workflow-graph").then((m) => m.WorkflowGraph), { ssr: false });

const ROLE_ORDER = ["agent", "support_operator", "reviewer", "senior_reviewer", "administrator"];

export default function ArchitecturePage() {
  const [architecture, setArchitecture] = useState<Architecture | null>(null);
  const [selected, setSelected] = useState<string | null>("orchestrator");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.architecture().then(setArchitecture).catch((err) => setError(err instanceof Error ? err.message : "Failed to load"));
  }, []);

  const component = architecture?.components.find((c) => c.id === selected) ?? null;

  return (
    <AppShell>
      <PageHeader
        title="Architecture Explorer"
        description="The implemented system, described by the running code: component map, trust boundaries, the live tool catalogue, the state-transition table and the permission matrix."
      />
      <ErrorBanner message={error} />
      {!architecture ? (
        <div className="flex justify-center py-20">
          <Spinner className="h-6 w-6" />
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid gap-6 xl:grid-cols-3">
            <Card className="xl:col-span-2">
              <CardHeader title="Component map" description="Click a component to highlight its dependencies." />
              <CardBody>
                <ArchitectureGraph architecture={architecture} selected={selected} onSelect={setSelected} />
              </CardBody>
            </Card>
            <Card>
              <CardHeader title={component?.name ?? "Select a component"} description={component?.path} />
              <CardBody className="space-y-4 text-sm">
                {component ? (
                  <>
                    <Badge tone="info">{component.layer}</Badge>
                    <p className="text-muted">{component.responsibility}</p>
                    <div>
                      <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-subtle">Talks to</div>
                      <ul className="space-y-1 text-xs">
                        {architecture.edges
                          .filter((e) => e.source === component.id || e.target === component.id)
                          .map((e) => (
                            <li key={`${e.source}-${e.target}`} className="font-mono text-muted">
                              {e.source === component.id ? "→" : "←"} {e.source === component.id ? e.target : e.source}
                              <span className="text-subtle"> · {e.label}</span>
                            </li>
                          ))}
                      </ul>
                    </div>
                  </>
                ) : null}
                <div className="rounded-md border border-border bg-background p-3 text-xs">
                  <div className="text-[11px] font-medium uppercase tracking-wide text-subtle">AI provider in use</div>
                  <div className="mt-1 font-mono text-muted">
                    {architecture.ai_provider.name} · {architecture.ai_provider.model} · {architecture.ai_provider.mode}
                  </div>
                </div>
              </CardBody>
            </Card>
          </div>
          <Card>
            <CardHeader title="Trust boundaries" description="Where untrusted input is separated from trusted decisions." />
            <CardBody className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {architecture.trust_boundaries.map((b) => (
                <div key={b.name} className="rounded-md border border-border bg-background p-3">
                  <div className="text-sm font-medium">{b.name}</div>
                  <p className="mt-1 text-xs text-muted">{b.description}</p>
                </div>
              ))}
            </CardBody>
          </Card>
          <Card>
            <CardHeader
              title="Workflow state machine"
              description="Read live from the orchestrator's transition table. Solid edges: the main flow. Dotted edges: any in-flight state can fail or be cancelled, and FAILED resumes into the step recorded in its checkpoint."
            />
            <CardBody>
              <WorkflowGraph transitionTable={architecture.state_transitions} />
            </CardBody>
          </Card>
          <Card>
            <CardHeader title="Tool catalogue" description="Every tool the agent can request, with the permission it needs, the states in which it may run and how failures are handled." />
            <Table>
              <thead>
                <tr>
                  <Th>Tool</Th>
                  <Th>Permission</Th>
                  <Th>Allowed states</Th>
                  <Th>Side effect</Th>
                  <Th>Retries</Th>
                  <Th>Failure behavior</Th>
                </tr>
              </thead>
              <tbody>
                {architecture.tools.map((tool) => (
                  <Tr key={tool.name}>
                    <Td>
                      <div className="font-mono text-xs text-accent">{tool.name}</div>
                      <div className="mt-0.5 max-w-sm text-xs text-muted">{tool.description}</div>
                    </Td>
                    <Td className="font-mono text-xs">{tool.permission}</Td>
                    <Td className="font-mono text-xs">{tool.allowed_states ? tool.allowed_states.join(", ") : "any"}</Td>
                    <Td>
                      <Badge tone={tool.side_effect ? "warning" : "neutral"}>{tool.side_effect ? (tool.idempotent ? "yes · idempotent" : "yes") : "read-only"}</Badge>
                    </Td>
                    <Td className="font-mono text-xs">{tool.max_attempts}</Td>
                    <Td className="max-w-xs text-xs text-muted">{tool.failure_behavior}</Td>
                  </Tr>
                ))}
              </tbody>
            </Table>
          </Card>
          <Card>
            <CardHeader title="Permission matrix" description="Enforced by the API dependencies, the tool registry and the approval service." />
            <Table>
              <thead>
                <tr>
                  <Th>Permission</Th>
                  {ROLE_ORDER.map((role) => (
                    <Th key={role} className="text-center">
                      {roleLabel(role)}
                    </Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {architecture.permission_matrix.map((row) => (
                  <Tr key={row.permission}>
                    <Td className="font-mono text-xs">{row.permission}</Td>
                    {ROLE_ORDER.map((role) => (
                      <Td key={role} className="text-center">
                        {row.roles[role] ? <Check className="mx-auto h-4 w-4 text-success" aria-label="granted" /> : <Minus className="mx-auto h-4 w-4 text-border-strong" aria-label="not granted" />}
                      </Td>
                    ))}
                  </Tr>
                ))}
              </tbody>
            </Table>
          </Card>
        </div>
      )}
    </AppShell>
  );
}
