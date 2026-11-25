"use client";

import { Background, Controls, type Edge, type Node, ReactFlow } from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo } from "react";

import type { Architecture } from "@/lib/types";

const LAYER_ORDER = ["presentation", "api", "security", "agent", "governance", "business", "observability", "evaluation", "data"];

// Hand-tuned grid (column * 250, row * 110) for the components that exist today; anything
// new falls back to a row per layer underneath, so the map never hides a component.
const GRID: Record<string, [number, number]> = {
  frontend: [1.5, 0],
  api: [1.5, 1],
  auth: [0.5, 2],
  orchestrator: [1.5, 2],
  lab: [2.5, 2],
  scanner: [0, 3],
  provider: [1, 3],
  tools: [2, 3],
  approvals: [3, 3],
  policy: [0, 4],
  business: [1, 4],
  workflows: [2, 4],
  audit: [3, 4],
  database: [1.5, 5],
};

const LAYER_COLORS: Record<string, string> = {
  presentation: "#4f8cff",
  api: "#3987e5",
  security: "#d03b3b",
  agent: "#9085e9",
  governance: "#fab219",
  business: "#0ca30c",
  observability: "#199e70",
  evaluation: "#d95926",
  data: "#a1a1aa",
};

export function ArchitectureGraph({
  architecture,
  selected,
  onSelect,
}: {
  architecture: Architecture;
  selected: string | null;
  onSelect: (id: string) => void;
}) {
  const { nodes, edges } = useMemo(() => {
    const byLayer = new Map<string, Architecture["components"]>();
    for (const component of architecture.components) {
      const list = byLayer.get(component.layer) ?? [];
      list.push(component);
      byLayer.set(component.layer, list);
    }
    const nodes: Node[] = [];
    let fallbackRow = 6;
    const place = (component: Architecture["components"][number], x: number, y: number) => {
      const color = LAYER_COLORS[component.layer] ?? "#4f8cff";
      const isSelected = component.id === selected;
      nodes.push({
        id: component.id,
        position: { x, y },
        data: { label: component.name },
        style: {
          width: 220,
          padding: "12px 12px",
          borderRadius: 8,
          fontSize: 13,
          fontWeight: 600,
          textAlign: "center",
          background: isSelected ? color : "#141418",
          color: isSelected ? "#0b0b0d" : "#f4f4f5",
          border: `1.5px solid ${color}`,
          boxShadow: isSelected ? `0 0 0 4px ${color}33` : undefined,
          cursor: "pointer",
        },
      });
    };
    for (const component of architecture.components) {
      const cell = GRID[component.id];
      if (cell) place(component, cell[0] * 250, cell[1] * 110);
    }
    for (const layer of LAYER_ORDER) {
      const extras = (byLayer.get(layer) ?? []).filter((c) => !GRID[c.id]);
      extras.forEach((component, index) => place(component, index * 250, fallbackRow * 110));
      if (extras.length) fallbackRow += 1;
    }
    const edges: Edge[] = architecture.edges.map((edge) => {
      const highlighted = selected !== null && (edge.source === selected || edge.target === selected);
      return {
        id: `${edge.source}->${edge.target}`,
        source: edge.source,
        target: edge.target,
        label: highlighted ? edge.label : undefined,
        className: highlighted ? "taken" : undefined,
        animated: highlighted,
        style: highlighted ? undefined : { opacity: selected ? 0.2 : 0.6 },
        labelStyle: { fill: "#a1a1aa", fontSize: 10 },
        labelBgStyle: { fill: "#0b0b0d" },
      };
    });
    return { nodes, edges };
  }, [architecture, selected]);

  return (
    <div className="h-[560px] w-full rounded-md border border-border bg-background">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        fitView
        fitViewOptions={{ padding: 0.1 }}
        nodesConnectable={false}
        nodesDraggable={false}
        panOnScroll
        onNodeClick={(_, node) => onSelect(node.id)}
        proOptions={{ hideAttribution: true }}
        colorMode="dark"
      >
        <Background gap={24} color="#2b2b30" />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
