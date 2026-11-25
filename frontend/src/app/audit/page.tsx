"use client";

import { useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Input, Select } from "@/components/ui/input";
import { EmptyState, ErrorBanner, PageHeader } from "@/components/ui/misc";
import { EventTimeline } from "@/components/workflow-bits";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";

const CATEGORIES = ["workflow", "agent", "tool", "policy", "approval", "execution", "security", "evaluation", "system"];

export default function AuditPage() {
  const [category, setCategory] = useState("");
  const [severity, setSeverity] = useState("");
  const [workflowId, setWorkflowId] = useState("");
  const { data, error, refresh } = useQuery(
    () => api.events({ category, severity, workflow_id: workflowId.trim(), limit: 200 }),
    [category, severity, workflowId],
  );
  const events = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <AppShell>
      <PageHeader
        title="Audit Timeline"
        description="Chronological, structured record of what the agent saw, proposed, was allowed to do, was denied, and what humans decided."
        actions={
          <Button variant="secondary" size="sm" onClick={refresh}>
            Refresh
          </Button>
        }
      />
      <ErrorBanner message={error} />
      <Card>
        <CardHeader
          title={`${total} event${total === 1 ? "" : "s"}`}
          description="Newest first · showing up to 200"
          actions={
            <div className="flex flex-wrap items-center gap-2">
              <Input value={workflowId} onChange={(e) => setWorkflowId(e.target.value)} placeholder="Workflow id" className="w-72 font-mono text-xs" aria-label="Filter by workflow id" />
              <Select value={category} onChange={(e) => setCategory(e.target.value)} className="w-40" aria-label="Filter by category">
                <option value="">All categories</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </Select>
              <Select value={severity} onChange={(e) => setSeverity(e.target.value)} className="w-36" aria-label="Filter by severity">
                <option value="">All severities</option>
                <option value="info">info</option>
                <option value="warning">warning</option>
                <option value="error">error</option>
              </Select>
            </div>
          }
        />
        {events.length === 0 ? <EmptyState title="No events match" /> : <EventTimeline events={events} />}
      </Card>
    </AppShell>
  );
}
