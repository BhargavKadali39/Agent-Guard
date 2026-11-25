"use client";

import { Background, Controls, type Edge, type Node, Position, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";

import type { WorkflowState } from "@/lib/types";

// Mirrors backend/app/workflows/states.py (also served live by /api/architecture).
const TRANSITIONS: Record<WorkflowState, WorkflowState[]> = {
  CREATED: ["ANALYZING", "CANCELLED", "FAILED"],
  ANALYZING: ["VERIFYING", "FAILED", "CANCELLED"],
  VERIFYING: ["POLICY_CHECK", "REJECTED", "FAILED", "CANCELLED"],
  POLICY_CHECK: ["AWAITING_APPROVAL", "APPROVED", "REJECTED", "FAILED", "CANCELLED"],
  AWAITING_APPROVAL: ["APPROVED", "REJECTED", "CANCELLED"],
  APPROVED: ["EXECUTING", "FAILED", "CANCELLED"],
  EXECUTING: ["COMPLETED", "FAILED"],
  FAILED: ["ANALYZING", "VERIFYING", "POLICY_CHECK", "EXECUTING", "CANCELLED"],
  COMPLETED: [],
  REJECTED: [],
  CANCELLED: [],
};

const POSITIONS: Record<WorkflowState, { x: number; y: number }> = {
  CREATED: { x: 0, y: 150 },
  ANALYZING: { x: 200, y: 150 },
  VERIFYING: { x: 400, y: 150 },
  POLICY_CHECK: { x: 600, y: 150 },
  AWAITING_APPROVAL: { x: 800, y: 30 },
  APPROVED: { x: 1000, y: 150 },
  EXECUTING: { x: 1200, y: 150 },
  COMPLETED: { x: 1400, y: 150 },
  REJECTED: { x: 1000, y: 290 },
  FAILED: { x: 600, y: 400 },
  CANCELLED: { x: 200, y: 400 },
};

// Transitions into FAILED / CANCELLED and resume paths out of FAILED exist from almost
// every state; drawing them all hides the main flow, so they are shown only when taken
// (workflow view) or as faint dotted lines (full state-machine view).
function isExceptional(from: string, to: string): boolean {
  return to === "FAILED" || to === "CANCELLED" || from === "FAILED";
}

const COLORS: Record<string, string> = {
  COMPLETED: "#0ca30c",
  REJECTED: "#d03b3b",
  FAILED: "#ec835a",
  CANCELLED: "#71717a",
  AWAITING_APPROVAL: "#fab219",
};

export interface TransitionRecord {
  from: string;
  to: string;
}

export function WorkflowGraph({
  current,
  transitions,
  transitionTable,
}: {
  current?: WorkflowState | null;
  transitions?: TransitionRecord[];
  transitionTable?: { from: string; to: string[] }[];
}) {
  const { nodes, edges } = useMemo(() => {
    const table: Record<string, string[]> = transitionTable
      ? Object.fromEntries(transitionTable.map((row) => [row.from, row.to]))
      : TRANSITIONS;
    const visited = new Set<string>(transitions?.flatMap((t) => [t.from, t.to]) ?? []);
    const takenEdges = new Set((transitions ?? []).map((t) => `${t.from}->${t.to}`));
    const nodes: Node[] = (Object.keys(POSITIONS) as WorkflowState[]).map((state) => {
      const isCurrent = state === current;
      const wasVisited = visited.has(state);
      const accent = COLORS[state] ?? "#4f8cff";
      return {
        id: state,
        position: POSITIONS[state],
        data: { label: state.replace(/_/g, " ") },
        draggable: false,
        sourcePosition: Position.Right,
        targetPosition: Position.Left,
        style: {
          width: 150,
          padding: "10px 12px",
          borderRadius: 8,
          fontSize: 12,
          fontFamily: "var(--font-mono)",
          fontWeight: 600,
          letterSpacing: "0.02em",
          textAlign: "center",
          background: isCurrent ? accent : wasVisited ? "#1b1b21" : "#141418",
          color: isCurrent ? "#0b0b0d" : wasVisited ? "#f4f4f5" : "#71717a",
          border: `1.5px solid ${isCurrent || wasVisited ? accent : "#2b2b30"}`,
          boxShadow: isCurrent ? `0 0 0 4px ${accent}33` : undefined,
        },
      };
    });
    const showAll = !transitions;
    const edges: Edge[] = [];
    for (const [from, targets] of Object.entries(table)) {
      for (const to of targets) {
        const taken = takenEdges.has(`${from}->${to}`);
        const exceptional = isExceptional(from, to);
        if (exceptional && !taken && !showAll) continue;
        edges.push({
          id: `${from}->${to}`,
          source: from,
          target: to,
          type: "smoothstep",
          className: taken ? "taken" : undefined,
          animated: taken,
          style: taken ? undefined : exceptional ? { strokeDasharray: "2 5", opacity: 0.35 } : { opacity: 0.6 },
          label: taken && from === "FAILED" ? "resume" : undefined,
          labelStyle: { fill: "#a1a1aa", fontSize: 10 },
          labelBgStyle: { fill: "#0b0b0d" },
        });
      }
    }
    return { nodes, edges };
  }, [current, transitions, transitionTable]);

  return (
    <div className="h-[380px] w-full rounded-md border border-border bg-background">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.15 }}
        nodesConnectable={false}
        elementsSelectable={false}
        panOnScroll
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background gap={24} color="#2b2b30" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
