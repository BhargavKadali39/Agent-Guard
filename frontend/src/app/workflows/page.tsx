"use client";

import { RefreshCw } from "lucide-react";
import { useState } from "react";

import { AppShell } from "@/components/app-shell";
import { Button } from "@/components/ui/button";
import { Card, CardHeader } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { ErrorBanner, PageHeader } from "@/components/ui/misc";
import { WorkflowTable } from "@/components/workflow-bits";
import { api } from "@/lib/api";
import { useQuery } from "@/lib/use-query";
import { HAPPY_PATH } from "@/lib/utils";

const STATES = [...HAPPY_PATH, "REJECTED", "FAILED", "CANCELLED"];

export default function WorkflowsPage() {
  const [state, setState] = useState("");
  const [offset, setOffset] = useState(0);
  const limit = 25;
  const { data, error, loading, refresh } = useQuery(
    () => api.workflows({ state: state || undefined, limit, offset }),
    [state, offset],
  );
  const items = data?.items ?? [];
  const total = data?.total ?? 0;

  return (
    <AppShell>
      <PageHeader
        title="Workflow Explorer"
        description="Every refund request as a stateful workflow: current state, verified facts, policy decision, approvals and execution."
        actions={
          <Button variant="secondary" size="sm" onClick={refresh} disabled={loading}>
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} /> Refresh
          </Button>
        }
      />
      <ErrorBanner message={error} />
      <Card className="mt-4">
        <CardHeader
          title={`${total} workflow${total === 1 ? "" : "s"}`}
          actions={
            <Select
              value={state}
              onChange={(e) => {
                setOffset(0);
                setState(e.target.value);
              }}
              className="w-56"
              aria-label="Filter by state"
            >
              <option value="">All states</option>
              {STATES.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
          }
        />
        <WorkflowTable workflows={items} emptyText="No workflows match this filter." />
        {total > limit ? (
          <div className="flex items-center justify-between border-t border-border px-5 py-3 text-xs text-muted">
            <span>
              Showing {offset + 1}–{Math.min(offset + limit, total)} of {total}
            </span>
            <div className="flex gap-2">
              <Button variant="secondary" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>
                Previous
              </Button>
              <Button variant="secondary" size="sm" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>
                Next
              </Button>
            </div>
          </div>
        ) : null}
      </Card>
    </AppShell>
  );
}
