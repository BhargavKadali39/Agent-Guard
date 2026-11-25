import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AuditEvent } from "@/lib/types";

import { EventTimeline, StateBadge } from "./workflow-bits";

const event = (overrides: Partial<AuditEvent>): AuditEvent => ({
  id: 1,
  workflow_id: "wf",
  timestamp: "2026-11-15T10:00:00Z",
  category: "tool",
  event_type: "tool.executed",
  severity: "info",
  actor_type: "agent",
  actor_id: "agent:refund-agent",
  tool_name: "get_order_information",
  duration_ms: 12,
  authorization_outcome: "allowed",
  workflow_state: "VERIFYING",
  message: "Tool get_order_information succeeded",
  payload: null,
  ...overrides,
});

describe("StateBadge", () => {
  it("renders the state with underscores replaced", () => {
    render(<StateBadge state="AWAITING_APPROVAL" />);
    expect(screen.getByText("AWAITING APPROVAL")).toBeInTheDocument();
  });
});

describe("EventTimeline", () => {
  it("shows an empty state", () => {
    render(<EventTimeline events={[]} />);
    expect(screen.getByText(/No events recorded yet/)).toBeInTheDocument();
  });
  it("renders denied events with the denial marker", () => {
    render(
      <EventTimeline
        events={[
          event({ id: 1 }),
          event({
            id: 2,
            category: "security",
            event_type: "tool.authorization_denied",
            severity: "warning",
            authorization_outcome: "denied",
            tool_name: "update_customer_record",
            message: "Denied tool call update_customer_record",
          }),
        ]}
      />,
    );
    expect(screen.getByText("tool.authorization_denied")).toBeInTheDocument();
    expect(screen.getByLabelText("denied")).toBeInTheDocument();
    expect(screen.getByLabelText("allowed")).toBeInTheDocument();
    expect(screen.getAllByText("update_customer_record").length).toBeGreaterThan(0);
  });
});
